"""Retired source-human leg repair entrypoint (owner correction, 2026-09-21).

Use source-supported contact refinement with smooth whole-body translations.
Preserve GVHMR/V2 joint poses; do not run collision correction or leg IK.
See docs/CONTACT_REFINEMENT.md.
"""


def main():
    raise SystemExit(
        'Human 6D leg repair is retired. Preserve source poses and use '
        'contact-only smooth translation; see docs/CONTACT_REFINEMENT.md.'
    )


if __name__ == '__main__':
    main()
