"""Resolve registered reusable assets without loading Blender."""
import os
from pathlib import Path

from .io import digest, read


def resolve(asset_id, root=None):
    root = Path(root or os.environ.get('INDOOR_PROJECT_ROOT', Path(__file__).resolve().parents[2]))
    item = read(root / 'assets/registry.json')['assets'][asset_id]
    asset = root / item['path']
    if digest(asset) != item['sha256']:
        raise ValueError('Registered asset checksum differs; validate and republish the current library before use')
    return asset.resolve()


def resolve_item(item_id, root=None, expected_kind=None):
    """Resolve an indexed item, validating current metadata and library SHA-256.

    This hashes the Blender library.
    The text index is derived; it is never an authority for an unregistered asset.
    """
    root = Path(root or os.environ.get('INDOOR_PROJECT_ROOT', Path(__file__).resolve().parents[2]))
    index = read(root / 'assets/index.json')
    matches = [item for item in index['entries'] if item['id'] == item_id]
    if len(matches) != 1:
        raise ValueError('Unknown or ambiguous indexed asset ID: ' + str(item_id))
    card = dict(matches[0])
    if card.get('status') != 'registered':
        raise ValueError('{} is {}; extract, normalize, validate and register it before replacement'.format(
            item_id, card.get('status', 'unregistered')))
    if expected_kind and card['kind'] != expected_kind:
        raise ValueError('{} is {}, expected {}'.format(item_id, card['kind'], expected_kind))
    library_id = card['library_id']
    registry = read(root / 'assets/registry.json')['assets']
    if library_id not in registry:
        raise ValueError('Asset index is stale: library is no longer registered')
    library = registry[library_id]
    for relative in ('assets/registry.json', library['metadata'], 'assets/catalog_sources.json'):
        recorded = index.get('input_sha256', {}).get(relative)
        if recorded is None or digest(root / relative) != recorded:
            raise ValueError('Asset index is stale; rebuild it before resolving ' + item_id)
    review_path = 'assets/orientation_reviews.json'
    if (root / review_path).exists() or review_path in index.get('input_sha256', {}):
        if not (root / review_path).exists() or digest(root / review_path) != index.get('input_sha256', {}).get(review_path):
            raise ValueError('Asset orientation index is stale; rebuild it before resolving ' + item_id)
    manifest = read(root / library['metadata'])
    pointer = card['source']['pointer'].strip('/').split('/')
    try:
        metadata = manifest[pointer[0]][int(pointer[1])]
    except (KeyError, IndexError, ValueError):
        raise ValueError('Asset index manifest pointer is stale: ' + item_id)
    if metadata['name'] != card['datablock'] or card['library_sha256'] != library['sha256']:
        raise ValueError('Asset index does not match registry/manifest: ' + item_id)
    card['library'] = str(resolve(library_id, root=root))
    card['manifest_item'] = metadata
    card['manifest_sha256'] = digest(root / library['metadata'])
    if card['kind'] == 'collection':
        from .orientation import normalize_orientation, unknown_orientation
        orientation = metadata.get('orientation', unknown_orientation())
        if (root / review_path).exists():
            review = read(root / review_path)['reviews'].get(item_id)
            if review:
                if review['library_sha256'] != library['sha256'] or review['datablock'] != metadata['name']:
                    raise ValueError('Orientation review belongs to different asset bytes: ' + item_id)
                orientation = review['orientation']
        orientation = normalize_orientation(orientation)
        if orientation != card.get('orientation'):
            raise ValueError('Asset orientation metadata is stale or inconsistent: ' + item_id)
        card['orientation'] = orientation
    return card


def collection_orientation(library, datablock, root=None):
    """Find hash-verified item orientation for a low-level registered import."""
    root = Path(root or os.environ.get('INDOOR_PROJECT_ROOT', Path(__file__).resolve().parents[2]))
    if not (root / 'assets/index.json').exists():
        return None
    path = Path(library).resolve()
    matches = [entry for entry in read(root / 'assets/index.json')['entries']
               if entry.get('kind') == 'collection' and entry.get('status') == 'registered'
               and entry['datablock'] == datablock and (root / entry['library_path']).resolve() == path]
    if len(matches) > 1:
        raise ValueError('Ambiguous registered collection; use its item ID through place_asset')
    return resolve_item(matches[0]['id'], root=root)['orientation'] if matches else None
