"""Prepare an exchange package as a local workspace for a new WorkBuddy task."""
import argparse
import json
from pathlib import Path

import agent_rehome
from cli_output import configure, print
from project_io import check_space, chunks, measure, write_checked
from project_rehome import is_migration_metadata, load_manifest, safe


def prepare(package, destination, *, target_agent='workbuddy'):
    package, destination = package.resolve(), destination.resolve()
    if destination.exists() or destination.is_relative_to(package):
        raise ValueError('Choose a new workspace outside the package directory')
    manifest = load_manifest(package)
    if manifest.get('file_references') is not None or manifest.get('native_sessions'):
        raise ValueError('Use a portable project package with copied files')
    history_root = '.rehome/exchange'
    plans = {}
    for group in ('files', 'attachments'):
        prefix = 'project/' if group == 'files' else 'attachments/'
        for entry in manifest[group]:
            relative = entry['path']
            if not relative.startswith(prefix):
                raise ValueError('Unexpected package file prefix')
            if group == 'files' and is_migration_metadata(relative[len(prefix):]):
                continue
            source = safe(package, relative)
            target = safe(destination, relative[len(prefix):] if group == 'files' else '.rehome/' + relative)
            key = str(target).casefold()
            expected = (entry['sha256'], entry['bytes'])
            if measure(chunks(source)) != expected:
                raise ValueError('Failed checksum: ' + relative)
            if key in plans and (group != 'attachments' or plans[key][2] != expected):
                raise ValueError('Conflicting workspace output: ' + relative)
            plans[key] = (source, target, expected)
    chats = {}
    for bundle in manifest['conversations']:
        agent_rehome.validate(bundle)
        sid = bundle['source']['session_id']
        chat = safe(destination, f'{history_root}/{sid}.json')
        if chat in chats or str(chat).casefold() in plans:
            raise ValueError('Duplicate conversation output')
        for turn in bundle['turns']:
            for item in turn['user'].get('attachments', []):
                path = safe(destination, '.rehome/' + item['path'])
                planned = plans.get(str(path).casefold())
                if not planned or planned[2] != (item['sha256'], item['bytes']):
                    raise ValueError('Unlisted historical attachment')
                item['workspace_path'] = path.relative_to(destination).as_posix()
        chats[chat] = bundle

    receipt = safe(destination, f'.rehome/restore-{target_agent}.json')
    if str(receipt).casefold() in plans:
        raise ValueError('Project file collides with the workspace receipt')
    for _, target, _ in plans.values():
        if any(str(parent).casefold() in plans for parent in target.parents):
            raise ValueError('Project output files collide with a directory')
    for generated in (*chats, receipt):
        if any(str(parent).casefold() in plans for parent in generated.parents):
            raise ValueError('Workspace metadata collides with a project file')
    check_space([(destination, sum(expected[1] for _, _, expected in plans.values())
                  + sum(len(json.dumps(bundle, ensure_ascii=False).encode('utf-8')) * 2
                        for bundle in chats.values()))])
    destination.mkdir(parents=True)
    for source, target, expected in plans.values():
        target.parent.mkdir(parents=True, exist_ok=True)
        write_checked(target, chunks(source), expected)
    for chat, bundle in chats.items():
        agent_rehome.dump(chat, bundle)
    result = {'status': 'workspace-ready', 'workspace': str(destination),
              'files': len(manifest['files']), 'attachments': len(manifest['attachments']),
              'chats': [{'path': path.relative_to(destination).as_posix(), 'title': bundle['title']}
                        for path, bundle in chats.items()],
              'native_history_registered': False}
    agent_rehome.dump(receipt, result)
    return result


def main():
    configure()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package', type=Path)
    parser.add_argument('--cwd', required=True, type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(prepare(args.package, args.cwd), ensure_ascii=False))
    except (ValueError, KeyError, OSError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
