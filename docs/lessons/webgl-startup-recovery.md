# WebGL context creation: client failure remains unconfirmed

On 2026-09-20 the user reported `Error creating WebGL context` even after the
single-view integration passed host-browser tests. The user confirmed that the
original website's interactive 3D scene rotates in the same browser. Therefore
browser-wide lack of WebGL is not an established explanation. Website and prior
review bundles both used Three.js r180 with antialiasing and a preserved drawing
buffer. The original client failure has not been reproduced on this host.

`renderer.js` tries three WebGL2 profiles on fresh canvases: standard, reduced
resource use without antialiasing/preserved drawing buffer, then low-power GPU
preference. Any allocated failed context is released. A successful compatibility
profile selects Fast lighting. This is a bounded startup fallback, not proof
that the client's failure is fixed, and it does not implement WebGL1 support.

Real `webglcontextcreationerror` messages and attempt attributes are recorded in
`window.roomkitRendererDiagnostic`. The review portal exposes and copies them
on failure. A standalone viewer link remains available to compare embedded and
top-level loading. Scene-data errors remain distinct from context errors.

Host validation: three unit tests; default headless Chromium without forced
software flags; explicit SwiftShader; deliberate standard-profile rejection;
deliberate total rejection followed by successful retry; and an actual
`--disable-webgl` negative case. The negative cases must show failure, never
Ready. The simulated rejections are tests of recovery, not reproductions of the
user's failure. All 11 motion entries also passed the existing source-frame,
actor visibility, G1 stage/light, playback, orbit and mobile-width checks.

Local evidence is under
`runs/_tools/all-people-reconstruction/20260920/interactive/`:
`qa-renderer-r3/validation.json`, `qa-r3/validation.json`, and screenshots.
Current candidate: `viewer-r3/`. Stable entry: <http://localhost:8793/interactive/>.
An unmodified copy of the website waterfront viewer is available at
<http://localhost:8793/interactive/website-control/demo-fast.html> solely as a
same-origin diagnostic control. Its four files were compared byte-for-byte to
the user's website directory, and it starts in default host Chromium. It is
not a fork used to generate the motion viewers. Source website files are
unchanged; dependency notices remain in its original bundle.

Client verification is still required. If the candidate fails, compare its
standalone link with the same-origin website control and retain the displayed
creation-event diagnostics. Do not replace this evidence with another blanket
instruction to enable WebGL or claim software-renderer tests establish client
GPU compatibility.
