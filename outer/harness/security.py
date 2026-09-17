"""Explicit child environments. The provider credential belongs to the gateway only."""
import os


def child_environment(extra=None):
    allowed = {'PATH', 'PATHEXT', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'TEMP', 'TMP',
               'HOME', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'PROGRAMFILES',
               'PROGRAMFILES(X86)', 'PROGRAMDATA', 'DOTNET_ROOT', 'NUGET_PACKAGES',
               'DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_CONFIG', 'LANG', 'LC_ALL'}
    result = {k: v for k, v in os.environ.items() if k.upper() in allowed}
    result.update(DOTNET_CLI_TELEMETRY_OPTOUT='1', DOTNET_NOLOGO='1',
                  PYTHONIOENCODING='utf-8', PYTHONUTF8='1')
    result.update(extra or {})
    return result
