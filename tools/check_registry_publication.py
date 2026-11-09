"""Validate public-repository publishing and GHCR package ownership.

This check reads metadata only. A GitHub Container Registry package's visibility
is separate from source visibility; changing it to public is a package-admin
action in GitHub's UI. Keep package authentication and identity checks intact.
"""
import argparse
import json
import os
import re
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def fetch(path, token):
    request = Request('https://api.github.com/' + path, headers={
        'Accept': 'application/vnd.github+json',
        'Authorization': 'Bearer ' + token,
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': 'homebox-mcp-public-publisher',
    })
    try:
        with urlopen(request, timeout=20) as response:
            return json.load(response)
    except HTTPError as error:
        if error.code == 404:
            return None
        raise RuntimeError(f'Package metadata unavailable (HTTP {error.code}); refusing publish') from None


def check(repository, token, require_package=False, reader=fetch):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('Invalid repository')
    if not token:
        raise ValueError('Missing GitHub token')
    repo = reader('repos/' + repository, token)
    if not repo or repo.get('private') is not False:
        raise ValueError('Repository is not verified public')
    if repo.get('full_name') and repo['full_name'].lower() != repository.lower():
        raise ValueError('Repository identity mismatch')
    owner, name = repository.split('/')
    group = 'orgs' if repo.get('owner', {}).get('type') == 'Organization' else 'users'
    package = reader(f'{group}/{owner}/packages/container/{name.lower()}', token)
    if package is None:
        if require_package:
            raise ValueError('Published package could not be verified')
        return 'new-package'
    if (package.get('name', '').lower() != name.lower()
            or package.get('package_type') != 'container'
            or package.get('owner', {}).get('login', '').lower() != owner.lower()):
        raise ValueError('Package identity does not match requested container')
    linked = (package.get('repository') or {}).get('full_name')
    if linked and linked.lower() != repository.lower():
        raise ValueError('Package is linked to another repository')
    visibility = package.get('visibility')
    if visibility not in ('private', 'public'):
        raise ValueError('Unsupported package visibility')
    return 'public-package' if visibility == 'public' else 'private-package-needs-manual-public-setting'


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--require-package', action='store_true')
    args = parser.parse_args()
    try:
        result = check(os.environ.get('GITHUB_REPOSITORY', ''),
                       os.environ.get('GH_TOKEN', ''), args.require_package)
    except (ValueError, RuntimeError) as error:
        raise SystemExit(str(error))
    print('Package check:', result)
    if result != 'public-package' and args.require_package:
        print('::warning::GHCR package is not public yet. In GitHub package settings, choose Change visibility > Public before anonymous pulls.')
