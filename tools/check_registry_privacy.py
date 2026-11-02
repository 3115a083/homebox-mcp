"""Fail closed before publishing to a public repo or an existing public package.

Reads metadata only; never changes repository or package visibility.
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
        'User-Agent': 'homebox-mcp-private-publisher',
    })
    try:
        with urlopen(request, timeout=20) as response:
            return json.load(response)
    except HTTPError as error:
        if error.code == 404:
            return None
        raise RuntimeError(f'Privacy metadata unavailable (HTTP {error.code}); refusing publish') from None


def check(repository, token, require_package=False, reader=fetch):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('Invalid repository')
    if not token:
        raise ValueError('Missing GitHub token')
    repo = reader('repos/' + repository, token)
    if not repo or repo.get('private') is not True:
        raise ValueError('Repository is not verified private')
    owner, name = repository.split('/')
    group = 'orgs' if repo.get('owner', {}).get('type') == 'Organization' else 'users'
    package = reader(f'{group}/{owner}/packages/container/{name.lower()}', token)
    if package is None:
        if require_package:
            raise ValueError('Published package could not be verified')
        # GitHub creates a new GHCR package as private. Recheck after first push.
        return 'new-package'
    if package.get('visibility') != 'private':
        raise ValueError('Existing package is not private; refusing publish')
    if (package.get('name', '').lower() != name.lower()
            or package.get('package_type') != 'container'
            or package.get('owner', {}).get('login', '').lower() != owner.lower()):
        raise ValueError('Package identity does not match the requested private container')
    # The Packages REST response does not guarantee a repository field, even
    # for linked containers. Verify documented owner/name/type fields instead.
    # Reject a conflicting link if supplied; CI separately verifies OCI source
    # and revision labels before publishing with this repository's GITHUB_TOKEN.
    linked = (package.get('repository') or {}).get('full_name')
    if linked and linked.lower() != repository.lower():
        raise ValueError('Package is linked to another repository')
    return 'private-package'


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--require-package', action='store_true')
    args = parser.parse_args()
    try:
        result = check(os.environ.get('GITHUB_REPOSITORY', ''),
                       os.environ.get('GH_TOKEN', ''), args.require_package)
    except (ValueError, RuntimeError) as error:
        raise SystemExit(str(error))
    print('Privacy check:', result)
