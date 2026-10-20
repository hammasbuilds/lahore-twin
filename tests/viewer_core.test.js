// Unit checks for the viewer's pure functions (positions, device state, why-chains).
const assert = require("assert");
const core = require("../viewer/core.js");

const pts = [[0, 0], [3, 0], [3, 4]];
assert.deepStrictEqual(core.pointAlong(pts, 0).slice(0, 2), [0, 0]);
assert.deepStrictEqual(core.pointAlong(pts, 5).slice(0, 2), [3, 2]);
assert.deepStrictEqual(core.pointAlong(pts, 99), [3, 4, false]);

const R = {
  people: [{ id: "a", arrive: 100, leave: 900 }],
  trips: [{ p: "a", t: 100, v: 1, pts: [[0, 0], [10, 0]] }, { p: "a", t: 500, v: 2, pts: [[10, 0], [10, 10]] }],
  labels: [[100, "a", "Arriving"], [800, "a", "Gone home"]],
  modes: { m: { devices: [[200, "r", "light", 1, 7], [400, "r", "light", 0, 9]],
                log: [{ id: 5, t: 199, topic: "office/r/motion", cause: null }, { id: 7, t: 200, topic: "office/r/light", cause: 5 },
                      { id: 9, t: 400, topic: "office/r/light", cause: 8 }] } },
};
const IX = core.buildIndex(R);
const a = IX.people.a;
assert.strictEqual(core.personAt(a, 50), null, "not here before arrival");
assert.deepStrictEqual([core.personAt(a, 104).x, core.personAt(a, 104).y], [4, 0]);
assert.deepStrictEqual([core.personAt(a, 503).x, core.personAt(a, 503).y], [10, 6]);
assert.strictEqual(core.personAt(a, 800), null, "gone after Gone home");
assert.strictEqual(core.deviceAt(IX.modes.m, "r", "light", 199).on, false);
assert.strictEqual(core.deviceAt(IX.modes.m, "r", "light", 200).on, true);
assert.strictEqual(core.deviceAt(IX.modes.m, "r", "light", 450).on, false);
assert.deepStrictEqual(core.whyChain(IX.modes.m, 7).map((m) => m.id), [7, 5]);
assert.deepStrictEqual(core.whyChain(IX.modes.m, 9).map((m) => m.id), [9], "missing cause ends the chain");
assert.strictEqual(core.clock(9 * 3600 + 5 * 60 + 59), "09:05");
// a stair hop drawn 40 m across the page but 8 m long: the walker waits at the bottom, then appears at the top
core.setHops([[2, 0, 42, 0, 8]]);
const up = [[0, 0], [2, 0], [42, 0], [45, 0]];
assert.deepStrictEqual(core.pointAlong(up, 6).slice(0, 2), [2, 0], "on the stairs: shown where they got on");
assert.deepStrictEqual(core.pointAlong(up, 11).slice(0, 2), [43, 0], "2 m + 8 m of stairs + 1 m");
core.setHops([]);
assert.deepStrictEqual(core.pointAlong(up, 11).slice(0, 2), [11, 0], "without the hop it is a straight line");
console.log("viewer core ok");
