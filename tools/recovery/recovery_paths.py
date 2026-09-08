"""Filesystem boundaries shared by additive recovery tools."""
import os
from pathlib import Path


def linked(path):
    return path.is_symlink() or path.is_junction()


def plain_path(path):
    """Represent Win32 DOS/UNC aliases identically; reject device namespaces."""
    path = Path(path)
    if os.name != 'nt':
        return path
    value = str(path)
    if value.startswith(('\\\\.\\', '\\??\\')):
        raise ValueError('Windows device paths are not recovery paths')
    if value.startswith('\\\\?\\'):
        value = value[4:]
        if value[:4].upper() == 'UNC\\':
            value = '\\\\' + value[4:]
        elif len(value) < 3 or not value[0].isalpha() or value[1:3] != ':\\':
            raise ValueError('Unsupported Windows path namespace')
    return Path(value)


def canonical_path(path, *, strict=False):
    # resolve() can return an extended Windows path even for an ordinary input.
    return plain_path(plain_path(path).resolve(strict=strict))


def checked_directory(path):
    path = plain_path(path).absolute()
    if any(linked(parent) for parent in (path, *path.parents)):
        raise ValueError('Recovery roots must not traverse links or junctions')
    path = canonical_path(path, strict=True)
    if not path.is_dir():
        raise ValueError('Recovery root must be a directory')
    return path


def snapshot_roots(source, project):
    source, project = checked_directory(source), checked_directory(project)
    if source == project or project.is_relative_to(source):
        raise ValueError('Snapshot must not contain the working project')
    if source.is_relative_to(project):
        recovery = project / 'work/FoldGPT-recovery'
        if source == recovery or not source.is_relative_to(recovery):
            raise ValueError('An in-project snapshot must be below work/FoldGPT-recovery')
    return source, project


def destination_boundary(destination, source, project, *, directory=False):
    """Check lexical paths before copying; never resolve through an output link."""
    destination, source, project = (plain_path(path).absolute() for path in (destination, source, project))
    destination.relative_to(project)
    if destination == source or destination.is_relative_to(source):
        raise ValueError('Recovery output would overwrite its own snapshot')
    if not directory and source.is_relative_to(destination):
        raise ValueError('Recovery output would replace an ancestor of its snapshot')
    parent = destination.parent
    while parent != project:
        if linked(parent) or (parent.exists() and not parent.is_dir()):
            raise ValueError('Unsafe existing recovery parent: ' + str(parent))
        parent = parent.parent
    if destination.is_junction():
        raise ValueError('Recovery output must not traverse a junction')


def checked_tree(root):
    """Enumerate without following symbolic links or Windows junctions."""
    for base, directories, files in os.walk(root, followlinks=False):
        for name in directories + files:
            if (Path(base) / name).is_junction():
                raise ValueError('Junction in recovery snapshot')
        yield Path(base), directories, files
