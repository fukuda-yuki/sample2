"""Dispatch mandatory browser contracts without changing historical cart meaning."""
from pathlib import Path
from . import browser_cart, education_browser, util


def _for(version):
    return education_browser if version == education_browser.VERSION else browser_cart


def required(version):
    return _for(version).required(version)


def coverage_complete(output):
    return _for(output.get('evaluationVersion')).coverage_complete(output)


def complete_evaluation(repo, condition, *args):
    return _for(condition['evaluation']['evaluation_version']).complete_evaluation(repo, condition, *args)


def _stored(directory):
    try:
        return _for(util.read_json(Path(directory)/'evaluation.json').get('evaluationVersion'))
    except (OSError, ValueError):
        return browser_cart


def execution_identity(directory):
    return _stored(directory).execution_identity(directory)


def stored_coverage_complete(directory, *args, **kwargs):
    return _stored(directory).stored_coverage_complete(directory, *args, **kwargs)


def stored_failure(directory, *args, **kwargs):
    return _stored(directory).stored_failure(directory, *args, **kwargs)
