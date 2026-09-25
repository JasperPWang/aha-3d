"""Structured visual judgment; supplying images is necessary, not proof of fidelity."""
import json
from pathlib import Path
import subprocess
import tempfile

from aha3d.io import digest, read, signature, write

ASPECTS = ('inventory', 'placement', 'dimensions', 'orientation', 'relationships', 'uncertainty')


def image_records(images):
    # The request is serialized with sort_keys=True. Attach in that same ID order
    # so a reviewer cannot assign a source image to a different camera or mode.
    return {key: {'path': str(Path(images[key]).resolve()), 'sha256': digest(images[key])}
            for key in sorted(images)}


def validate(review, revision, images, coverage=ASPECTS, subjects=(), object_views=None):
    if review.get('schema_version') != 2 or review.get('candidate_revision') != revision:
        raise ValueError('Visual review revision is missing or stale')
    if not review.get('reviewer', '').strip() or review.get('verdict') not in ('accepted', 'rejected'):
        raise ValueError('Visual reviewer and explicit verdict required')
    delivery = review.get('image_delivery', {})
    if delivery.get('method') != 'codex_exec_images' or delivery.get('images') != image_records(images):
        raise ValueError('Actual image delivery receipt missing or changed; run acceptance review-images')
    if not delivery.get('request_sha256'):
        raise ValueError('Image delivery must identify the reviewer request')
    if set(review.get('reviewed_views', [])) != set(images):
        raise ValueError('Required visual review views incomplete')
    observations = review.get('observations', [])
    for row in observations:
        if not row.get('observation', '').strip() or not row.get('subjects') or not row.get('views'):
            raise ValueError('Concrete observations need object/relationship IDs and supplied views')
        if not set(row['views']) <= set(images):
            raise ValueError('Observation refers to an unsupplied image')
    if not set(coverage) <= {r.get('aspect') for r in observations}:
        raise ValueError('Required visual review coverage incomplete')
    if not set(subjects) <= {s for r in observations for s in r['subjects']}:
        raise ValueError('Salient object/relationship review coverage incomplete')
    if not set(images) <= {v for r in observations for v in r['views']}:
        raise ValueError('Every required image needs concrete observations')
    for identity, focused in (object_views or {}).items():
        # A general paragraph listing all objects is not an individual inspection.
        observed = {v for row in observations if row['subjects'] == [identity]
                    for v in row['views']}
        if not focused or not set(focused) <= observed:
            raise ValueError('Object-focused observations missing: ' + identity)
    for key in ('findings', 'uncertainties', 'unreviewed_areas'):
        if not isinstance(review.get(key), list):
            raise ValueError('Explicit findings, uncertainties and unreviewed areas required')
    for uncertainty in review['uncertainties']:
        if not isinstance(uncertainty, dict) or not uncertainty.get('observation') or not uncertainty.get('impact'):
            raise ValueError('Uncertainty needs an observation and its acceptance impact')
    if review['verdict'] == 'accepted' and (review['unreviewed_areas'] or review['findings'] or
            any(u['impact'] != 'nonblocking' for u in review['uncertainties'])):
        raise ValueError('Unresolved findings, blocking uncertainty or unreviewed areas cannot be accepted')
    return review


def run_reviewer(request, output, *, executable='codex'):
    """Use the installed Codex image-input CLI, never a path-only review prompt.

    No automatic acceptance: failed/malformed/rejected judgments remain unaccepted.
    The caller supplies IDs -> images from a gate's evidence, not a replacement scene.
    """
    output = Path(output).resolve()
    if output.exists():
        raise ValueError('Review outputs are immutable; choose a new path')
    images = request['images']; before = image_records(images)
    prompt = ('Review the attached images in the supplied ID order. Return ONLY a JSON object. '
              'Do not infer correctness from scores or missing geometry. Use schema_version=2, '
              'candidate_revision, reviewer, verdict (accepted/rejected), reviewed_views (all image IDs), '
              'observations [{aspect, subjects:[object/relationship IDs], views:[image IDs], observation}], '
              'findings:[{id,severity:blocking/nonblocking,affected_ids:[...],views:[...],observation,resolution_needed}], uncertainties:[{observation,impact:nonblocking/blocking}], '
              'unreviewed_areas:[...]. Cover every required aspect and subject. For each object_views entry, '
              'provide observations with subjects:[that exact object ID] covering its focus images. '
              'Describe contour/extent, placement and supporting or neighboring geometry; do not substitute a whole-room verdict. '
              'Reject persistent discrepancies. '
              'Image delivery proves no judgment. Request: ' + json.dumps(request, sort_keys=True))
    with tempfile.TemporaryDirectory(prefix='indoor-review-') as temporary:
        raw = Path(temporary) / 'review.json'
        cmd = [executable, 'exec', '--ephemeral', '--sandbox', 'read-only', '--skip-git-repo-check',
               '--output-last-message', str(raw)]
        for image in before.values():
            cmd += ['--image', image['path']]
        # The prompt travels on stdin; image bytes are attached by Codex's image API.
        subprocess.run(cmd + ['-'], input=prompt, text=True, check=True, timeout=600)
        review = read(raw)
    if image_records(images) != before:
        raise ValueError('Images changed during visual review')
    review['image_delivery'] = dict(method='codex_exec_images', images=before, request_sha256=signature(request))
    validate(review, request['candidate_revision'], images, request.get('coverage', ASPECTS), request.get('subjects', []), request.get('object_views'))
    write(output, review)
    return dict(status='awaiting_review' if review['verdict'] == 'accepted' else 'blocked',
                accepted=False, review=str(output), verdict=review['verdict'],
                next_step='Record this judgment against the current gate; task acceptance is separate.')
