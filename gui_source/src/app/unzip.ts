/**
 * Just enough of the zip format to read what Dropbox's `download_zip` sends back.
 *
 * That endpoint is how the index is read from Dropbox: one request for the whole
 * `indexing` folder, where a request per fic would be thousands. The browser already does
 * the hard part - `DecompressionStream('deflate-raw')` inflates an entry - so all this does
 * is find the entries, which is a walk down the central directory at the end of the file.
 * A library would be a dependency for forty lines.
 *
 * Only what `download_zip` produces is handled: stored and deflated entries, no
 * encryption, no zip64. Anything else throws, and the caller falls back to reading the
 * files one at a time - slower, but it gets there.
 */

const END_OF_DIRECTORY = 0x06054b50;
const DIRECTORY_ENTRY = 0x02014b50;
const LOCAL_HEADER = 0x04034b50;
const STORED = 0;
const DEFLATED = 8;

export interface ZipEntry {
  /** the path inside the zip, folders and all */
  path: string;
  data: Uint8Array;
}

export async function unzip(buffer: ArrayBuffer): Promise<ZipEntry[]> {
  const view = new DataView(buffer);
  const bytes = new Uint8Array(buffer);
  const names = new TextDecoder('utf-8');

  // the end record sits in the last 22 bytes plus however long the zip's comment is
  let end = -1;
  for (let at = buffer.byteLength - 22; at >= Math.max(0, buffer.byteLength - 22 - 0xffff); at--) {
    if (view.getUint32(at, true) === END_OF_DIRECTORY) {
      end = at;
      break;
    }
  }
  if (end < 0) throw new Error('not a zip file');

  const count = view.getUint16(end + 10, true);
  let at = view.getUint32(end + 16, true);
  if (count === 0xffff || at === 0xffffffff) throw new Error('zip64 is not supported');

  const entries: ZipEntry[] = [];
  for (let i = 0; i < count; i++) {
    if (view.getUint32(at, true) !== DIRECTORY_ENTRY) throw new Error('damaged zip directory');
    const flags = view.getUint16(at + 8, true);
    const method = view.getUint16(at + 10, true);
    const compressed = view.getUint32(at + 20, true);
    const nameLength = view.getUint16(at + 28, true);
    const extraLength = view.getUint16(at + 30, true);
    const commentLength = view.getUint16(at + 32, true);
    const local = view.getUint32(at + 42, true);
    const path = names.decode(bytes.subarray(at + 46, at + 46 + nameLength));
    at += 46 + nameLength + extraLength + commentLength;

    if (path.endsWith('/')) continue; // a folder, not a file
    if (flags & 1) throw new Error('encrypted zips are not supported');
    if (view.getUint32(local, true) !== LOCAL_HEADER) throw new Error('damaged zip entry');

    // the local header repeats the name and may carry a different extra field, so the data
    // starts after *its* lengths, not the directory's
    const start = local + 30 + view.getUint16(local + 26, true) + view.getUint16(local + 28, true);
    const raw = bytes.subarray(start, start + compressed);

    if (method === STORED) entries.push({ path, data: raw.slice() });
    else if (method === DEFLATED) entries.push({ path, data: await inflate(raw) });
    else throw new Error(`zip compression method ${method} is not supported`);
  }
  return entries;
}

async function inflate(raw: Uint8Array): Promise<Uint8Array> {
  const stream = new Response(raw as BodyInit).body!.pipeThrough(new DecompressionStream('deflate-raw'));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}
