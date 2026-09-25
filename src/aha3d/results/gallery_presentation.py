"""Gallery-only curation and navigation previews; never selects deliveries."""
from pathlib import Path

from .registry import local


def curate(index):
    """Keep room reconstructions separate from tracking and tool experiments."""
    index['scenes'] = [r for r in index['scenes']
                       if not r['id'].startswith(('worldtrack_', 'adt_'))
                       and r['id'] != 'roomkit_variants_demo']
    rows = index['scenes']
    index['counts'] = dict(scenes=len(rows),
                           selected=sum(r['selection_status'] == 'selected' for r in rows),
                           candidates=sum(len(r['candidates']) for r in rows))


def preview_media(root, row):
    """Use selected media, then source footage, then labelled candidate media."""
    def usable(item):
        if item.get('availability') in ('missing', 'unavailable', 'changed', 'needs_verification'):
            return False
        if Path(item.get('path', '')).suffix.lower() not in ('.mp4', '.webm', '.mov', '.jpg', '.jpeg', '.png'):
            return False
        try:
            return local(root, item['path']).is_file()
        except (ValueError, OSError):
            return False

    groups = [(row['artifacts'], 'Selected result preview'),
              ([row['reference']] if row.get('reference') else [], 'Source video preview'),
              (row['candidates'], 'Candidate preview · not a selected delivery')]
    for items, label in groups:
        media = [a for a in items if usable(a)]
        # Prefer full-room renders over comparisons or human tracking diagnostics.
        media.sort(key=lambda a: (a.get('role') == 'thumbnail',
                                 not any(k in a['path'] for k in ('/delivery/', 'reconstruction.mp4', 'room_motion.mp4')),
                                 'comparison' in a['path'], a['path']))
        if media:
            row['preview_label'] = label
            return media
    return []
