"""File operations go here."""

import configparser
import datetime
import getpass
import importlib
import importlib.metadata
import importlib.resources
import json
import os

from source_code import parse_text, strings
from source_code.storage import LocalStorage


class FileOps:
    def __init__(self, storage=None):
        # These normally resolve against the working directory. A deployed bundle keeps
        # config and logs in folders of their own, and says so through the environment.
        # Unset, os.path.join('', name) gives back name, so the behaviour is unchanged.
        config_folder = os.environ.get(strings.ENV_CONFIG_FOLDER, '')
        log_folder = os.environ.get(strings.ENV_LOG_FOLDER, '')

        self.logfile = os.path.join(log_folder, strings.LOG_FOLDER_NAME, strings.LOG_FILE_NAME)
        self.inifile = os.path.join(config_folder, strings.INI_FILE_NAME)
        self.settingsfile = os.path.join(config_folder, strings.SETTINGS_FILE_NAME)
        # the library a run reads and writes: the one the web page has open, handed in as
        # `PageStorage`. there is no DownloadFolder setting any more - the page picks the
        # folder, and only the page can reach it. a FileOps made with no storage is for the
        # helper's own settings and log, and has no library at all.
        #
        # every path in the library is still built by joining onto `downloadfolder`, so
        # nothing that builds one has to know where the library really is
        self.storage = storage


    @property
    def downloadfolder(self) -> str:
        return self.storage.root if self.storage else ''


    @property
    def runsfolder(self) -> str:
        """Where run history is kept - inside the library, beside what it describes.

        Everything that walks the library has to skip it by name - `shared.scan_downloaded_works`
        does, and so does the web page, which would otherwise read a run record as a work: a
        record has an `id`, which is all `flattenRecord` needs to hand one back as a bookmark.
        """

        return os.path.join(self.downloadfolder, strings.RUNS_FOLDER_NAME)


    @property
    def worksfolder(self) -> str:
        """Where downloaded works are written and looked for - never the top level."""

        return os.path.join(self.downloadfolder, strings.WORKS_FOLDER_NAME)


    @downloadfolder.setter
    def downloadfolder(self, folder: str) -> None:
        # a plain folder, for code handed a path - the tests, mostly. a run's library comes
        # from the page
        if self.storage is None: self.storage = LocalStorage(folder)
        else: self.storage.root = folder


    def initialize(self) -> None:
        os.makedirs(os.path.dirname(self.logfile), exist_ok=True)
        # empty when config sits in the working directory, which needs no creating
        config_folder = os.path.dirname(self.inifile)
        if config_folder: os.makedirs(config_folder, exist_ok=True)
        if self.storage is not None:
            # the page set the library up when it opened it; this is a check it is still
            # reachable, and a repair if a folder has been deleted since
            self.storage.ensure_root()
            for name in strings.LIBRARY_FOLDER_NAMES:
                self.storage.make_dirs(os.path.join(self.downloadfolder, name))
        if not os.path.exists(self.inifile):
            with importlib.resources.open_text(strings.SETTINGS_FOLDER_NAME, strings.INI_FILE_NAME) as f:
                with open(self.inifile, 'w', encoding='utf-8') as ini_file:
                    ini_file.write(f.read())
        if (self.get_ini_value_boolean(strings.INI_PASSWORD_SAVE, False) == False):
            self.save_setting(strings.SETTING_PASSWORD, None)


    def update_ini(self) -> None:
        with open(self.inifile, 'r', encoding='utf-8') as l: 
            local = l.read()
        with importlib.resources.open_text(strings.SETTINGS_FOLDER_NAME, strings.INI_FILE_NAME) as r: 
            remote = r.read()
        ini_differences = self.ini_differences(local, remote)
        if ini_differences: self.save_new_ini(ini_differences)


    def ini_differences(self, local: str, remote: str) -> str | None:
        local_config = configparser.ConfigParser()
        local_config.read_string(local)
        remote_config = configparser.ConfigParser()
        remote_config.read_string(remote)
        local_config_structure = {section: set(local_config.options(section)) for section in local_config.sections()}
        remote_config_structure = {section: set(remote_config.options(section)) for section in remote_config.sections()}
        return self.ini_differences_str(local_config_structure, remote_config_structure)


    def ini_differences_str(self, local: dict[str, set[str]], remote: dict[str, set[str]]) -> str | None:
        if local == remote: return None
        message = strings.MESSAGE_INI_DIFFERENCES
        for section in list(local):
            if section not in remote:
                message += strings.MESSAGE_INI_REMOVED_SECTION.format(section)
                local.pop(section, None)
        for section in list(remote):
            if section not in local:
                message += strings.MESSAGE_INI_ADDED_SECTION.format(section)
                remote.pop(section, None)
        if local or remote:
            all_sections = set(local.keys()).union(remote.keys())
            for section in all_sections:
                local_keys = local.get(section, set())
                remote_keys = remote.get(section, set())
                added_keys = remote_keys - local_keys
                removed_keys = local_keys - remote_keys
                for key in added_keys:
                    message += strings.MESSAGE_INI_ADDED_KEY.format(key, section)
                for key in removed_keys:
                    message += strings.MESSAGE_INI_REMOVED_KEY.format(key, section)
        return message


    def save_new_ini(self, ini_differences: str) -> None:
        package_version = importlib.metadata.version('ao3downloader')
        new_inifile = f'settings-v{package_version}.ini'
        if not os.path.exists(new_inifile):
            with importlib.resources.open_text(strings.SETTINGS_FOLDER_NAME, strings.INI_FILE_NAME) as f:
                with open(new_inifile, 'w', encoding='utf-8') as ini_file:
                    ini_file.write(f.read())
            print(strings.MESSAGE_INI_FILE_CHANGED.format(new_inifile))
            print(ini_differences)


    def write_log(self, log: dict) -> None:
        log['timestamp'] = datetime.datetime.now().strftime(strings.TIMESTAMP_FORMAT)
        with open(self.logfile, 'a', encoding='utf-8') as f:
            json.dump(log, f, ensure_ascii=False)
            f.write('\n')


    def save_bytes(self, filename: str, content: bytes) -> str:
        """Write a downloaded file, and say where it went.

        The path is returned so a caller replacing an older copy can check the new one
        really arrived before removing anything.
        """

        file = os.path.join(self.downloadfolder, filename)
        self.storage.write_bytes(file, content)
        return file


    def saved_intact(self, path: str, expected_size: int) -> bool:
        """Whether a file really is on disk, at the full length it should be.

        Deleting the copy a download replaces is only safe once this says yes. A run that
        failed, was cut short, or wrote somewhere other than the folder in use must never
        take the existing copy with it.
        """

        try:
            return self.storage.size(path) == expected_size
        except Exception:
            return False


    def saved_problem(self, path: str, expected_size: int) -> str:
        """What is wrong with a file `saved_intact` said no to, in words for a report.

        Asked only after that answer, so a file that is fine in between is described as
        such rather than invented a fault for.
        """

        try:
            size = self.storage.size(path)
            if size is None:
                return strings.SAVED_NOT_FOUND.format(self.storage.describe(path))
            if size != expected_size:
                return strings.SAVED_WRONG_SIZE.format(expected_size, size)
            return strings.SAVED_FINE_ON_SECOND_LOOK
        except Exception as e:
            return strings.SAVED_UNREADABLE.format(e)


    def rename_file(self, old: str, new: str) -> bool:
        """Rename a file, reporting whether it worked.

        Refuses to write over something already at the new name: os.replace would silently
        destroy it. A file that cannot be renamed - open elsewhere, read only - is left
        exactly as it is rather than raising.
        """

        return self.storage.rename(old, new)


    def delete_file(self, path: str) -> bool:
        """Remove a file, reporting whether it went. A file already gone counts as done."""

        return self.storage.delete(path)


    def is_file(self, path: str) -> bool:
        try:
            return self.storage.is_file(path)
        except Exception:
            return False


    def exists(self, path: str) -> bool:
        return self.storage.exists(path)


    def list_files(self, folder: str) -> list[str]:
        """The names of the files directly inside a folder of the library."""

        return self.storage.list_files(folder)


    def same_file(self, a: str, b: str) -> bool:
        return self.storage.same_file(a, b)


    def describe(self, path: str) -> str:
        """A path in the library as a person would want to read it in a message."""

        return self.storage.describe(path)


    def read_text(self, path: str) -> str:
        return self.storage.read_bytes(path).decode('utf-8')


    def write_text(self, path: str, text: str) -> None:
        self.storage.write_bytes(path, text.encode('utf-8'))


    def load_json(self, filename: str) -> dict | None:
        """Read a json file from the downloads folder, or None if it isn't usable.

        A file that has been damaged is treated as absent rather than crashing the run;
        the next save replaces it.
        """

        file = os.path.join(self.downloadfolder, filename)
        try:
            content = json.loads(self.read_text(file))
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            return None
        return content if isinstance(content, dict) else None


    def save_json(self, filename: str, content) -> str:
        file = os.path.join(self.downloadfolder, filename)
        self.write_text(file, json.dumps(content, ensure_ascii=False, indent=2))
        return file


    def save_setting(self, setting: str, value) -> None:
        """Write one saved setting, or remove it when the value is None.

        **Removing something that was never there writes nothing.** `initialize` clears the
        saved password on every start whenever SavePassword is off - which is always, in a
        bundle, because the bundler strips that setting out - and this used to create a
        data.json holding `{}` to record the absence of a key that had never existed. The
        web ui keeps nothing here at all, so the file was pure litter in a config folder
        that is meant not to have one. See `get_settings_json`, which does not create on
        read for the same reason.
        """

        js = self.get_settings_json()
        if value is None:
            if setting not in js: return
            js.pop(setting, None)
        else:
            js[setting] = value
        with open(self.settingsfile, 'w') as f:
            f.write(json.dumps(js))


    def get_setting(self, setting: str):
        js = self.get_settings_json()
        try:
            return js[setting]
        except:
            return ''


    def get_settings_json(self) -> dict:
        """Saved settings, or nothing when none have been saved.

        Reading deliberately does not create the file. The web ui asks for the saved
        username every time the page loads, and it keeps nothing of its own here, so
        creating one on read left an empty data.json sitting in the config folder of a
        bundle that is meant not to have one. save_setting still creates it, which is
        what the console menu needs.
        """

        try:
            with open(self.settingsfile, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}


    def setting(self, prompt: str, setting: str, save: bool = True, sensitive: bool = False) -> str:
        value = self.get_setting(setting)
        if value == '':
            print(prompt)
            if sensitive:
                value = getpass.getpass()
            else:
                value = input()
            if save:
                self.save_setting(setting, value)
        return value


    def load_logfile(self) -> list[dict]:
        logs = []
        try:
            with open(self.logfile, 'r', encoding='utf-8') as f:
                objects = map(lambda x: json.loads(x), f.readlines())
                logs.extend(list(objects))
        except FileNotFoundError:
            pass
        return logs


    def get_ini_value(self, key: str, fallback: str, raw: bool = False) -> str:
        config = configparser.ConfigParser()
        config.read(self.inifile)
        return config.get(strings.INI_SECTION_NAME, key, fallback=fallback, raw=raw)


    def get_ini_value_boolean(self, key: str, fallback: bool) -> bool:
        config = configparser.ConfigParser()
        config.read(self.inifile)
        return config.getboolean(strings.INI_SECTION_NAME, key, fallback=fallback)


    def get_ini_value_integer(self, key: str, fallback: int) -> int:
        config = configparser.ConfigParser()
        config.read(self.inifile)
        return config.getint(strings.INI_SECTION_NAME, key, fallback=fallback)
