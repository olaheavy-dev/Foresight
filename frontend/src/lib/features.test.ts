import { fetchFeatures, parseFeatures } from "./features";

const valid = { features: [{ key: "forecast", stage: 1, title: "Forecast", enabled: false }] };

function respond(body: unknown, init: ResponseInit = { status: 200 }): typeof fetch {
  return async () => new Response(JSON.stringify(body), init);
}

describe("parseFeatures", () => {
  it("accepts a well-formed payload", () => {
    expect(parseFeatures(valid)).toEqual(valid.features);
  });

  it.each([
    null,
    {},
    { features: "nope" },
    { features: [{ key: "forecast", stage: "1", title: "Forecast", enabled: false }] },
    { features: [{ key: "forecast", stage: 1, title: "Forecast", enabled: "yes" }] },
  ])("rejects malformed payload %j", (body) => {
    expect(parseFeatures(body)).toBeNull();
  });
});

describe("fetchFeatures", () => {
  it("returns parsed features on success", async () => {
    expect(await fetchFeatures(respond(valid))).toEqual(valid.features);
  });

  it("returns null on a non-OK response", async () => {
    expect(await fetchFeatures(respond(valid, { status: 503 }))).toBeNull();
  });

  it("returns null when the payload is malformed", async () => {
    expect(await fetchFeatures(respond({ features: [{ key: 1 }] }))).toBeNull();
  });

  it("returns null when the network fails", async () => {
    const failing: typeof fetch = async () => {
      throw new TypeError("network down");
    };
    expect(await fetchFeatures(failing)).toBeNull();
  });

  it("gives up after the timeout", async () => {
    const hanging: typeof fetch = (_input, init) =>
      new Promise((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => reject(init.signal?.reason));
      });
    expect(await fetchFeatures(hanging, 20)).toBeNull();
  });
});
