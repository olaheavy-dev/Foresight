/**
 * Runtime validation against the generated contracts schema (docs/08 §6 Step 3).
 *
 * A small interpreter for the JSON Schema subset Pydantic emits ($ref, type, enum, const,
 * oneOf/anyOf with discriminators, properties, required, items, string/number/array bounds,
 * patterns, date formats). Unknown properties are tolerated by default: a newer server may add
 * optional fields within a major version (§11), and the client must keep rendering.
 */
import schemaJson from "./schema.json";

type Schema = {
  $ref?: string;
  type?: string | string[];
  enum?: unknown[];
  const?: unknown;
  oneOf?: Schema[];
  anyOf?: Schema[];
  allOf?: Schema[];
  discriminator?: { propertyName: string; mapping: Record<string, string | Schema> };
  properties?: Record<string, Schema>;
  required?: string[];
  additionalProperties?: boolean | Schema;
  items?: Schema;
  minItems?: number;
  maxItems?: number;
  minLength?: number;
  maxLength?: number;
  pattern?: string;
  format?: string;
  minimum?: number;
  maximum?: number;
  exclusiveMinimum?: number;
  exclusiveMaximum?: number;
};

export type SchemaError = { path: string; message: string };
export type ValidateOptions = { allowUnknownProperties?: boolean };

const defs = (schemaJson as unknown as { $defs: Record<string, Schema> }).$defs;
const patterns = new Map<string, RegExp>();
const DATE = /^\d{4}-\d{2}-\d{2}$/;
const DATE_TIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})?$/;

function resolve(ref: string): Schema {
  const name = ref.replace("#/$defs/", "");
  const def = defs[name];
  if (!def) throw new Error(`Unknown schema definition ${name}`);
  return def;
}

function typeOf(value: unknown): string {
  if (value === null) return "null";
  if (Array.isArray(value)) return "array";
  if (typeof value === "number") return Number.isInteger(value) ? "integer" : "number";
  return typeof value;
}

function typeMatches(expected: string, actual: string): boolean {
  return expected === actual || (expected === "number" && actual === "integer");
}

function check(schema: Schema, value: unknown, path: string, opts: ValidateOptions): SchemaError[] {
  if (schema.$ref) return check(resolve(schema.$ref), value, path, opts);
  const errors: SchemaError[] = [];
  const fail = (message: string) => errors.push({ path: path || "(root)", message });

  if (schema.discriminator && schema.oneOf) {
    const { propertyName, mapping } = schema.discriminator;
    const tag = (value as Record<string, unknown> | null)?.[propertyName];
    const target = typeof tag === "string" ? mapping[tag] : undefined;
    if (!target) {
      fail(`unknown ${propertyName} ${JSON.stringify(tag)}`);
      return errors;
    }
    return check(typeof target === "string" ? { $ref: target } : target, value, path, opts);
  }
  const alternatives = schema.oneOf ?? schema.anyOf;
  if (alternatives) {
    const results = alternatives.map((alt) => check(alt, value, path, opts));
    if (results.some((r) => r.length === 0)) return [];
    // Report the closest alternative (fewest errors) so messages stay actionable.
    return results.reduce((best, r) => (r.length < best.length ? r : best));
  }
  for (const part of schema.allOf ?? []) errors.push(...check(part, value, path, opts));

  const actual = typeOf(value);
  if (schema.type !== undefined) {
    const expected = Array.isArray(schema.type) ? schema.type : [schema.type];
    if (!expected.some((t) => typeMatches(t, actual))) {
      fail(`expected ${expected.join(" | ")}, got ${actual}`);
      return errors;
    }
  }
  if ("const" in schema && value !== schema.const) fail(`expected ${JSON.stringify(schema.const)}`);
  if (schema.enum && !schema.enum.includes(value)) {
    fail(`expected one of ${schema.enum.map((e) => JSON.stringify(e)).join(", ")}`);
  }

  if (typeof value === "string") {
    const length = [...value].length;
    if (schema.minLength !== undefined && length < schema.minLength) fail("too short");
    if (schema.maxLength !== undefined && length > schema.maxLength) fail("too long");
    if (schema.pattern) {
      let re = patterns.get(schema.pattern);
      if (!re) patterns.set(schema.pattern, (re = new RegExp(schema.pattern, "u")));
      if (!re.test(value)) fail(`does not match ${schema.pattern}`);
    }
    if (schema.format === "date" && !DATE.test(value)) fail("not a date");
    if (schema.format === "date-time" && !DATE_TIME.test(value)) fail("not a date-time");
  }
  if (typeof value === "number") {
    if (schema.minimum !== undefined && value < schema.minimum) fail(`below ${schema.minimum}`);
    if (schema.maximum !== undefined && value > schema.maximum) fail(`above ${schema.maximum}`);
    if (schema.exclusiveMinimum !== undefined && value <= schema.exclusiveMinimum) {
      fail(`not above ${schema.exclusiveMinimum}`);
    }
    if (schema.exclusiveMaximum !== undefined && value >= schema.exclusiveMaximum) {
      fail(`not below ${schema.exclusiveMaximum}`);
    }
  }
  if (Array.isArray(value)) {
    if (schema.minItems !== undefined && value.length < schema.minItems) fail("too few items");
    if (schema.maxItems !== undefined && value.length > schema.maxItems) fail("too many items");
    if (schema.items) {
      value.forEach((item, i) => errors.push(...check(schema.items!, item, `${path}.${i}`, opts)));
    }
  }
  if (actual === "object") {
    const record = value as Record<string, unknown>;
    for (const key of schema.required ?? []) {
      if (!(key in record)) errors.push({ path: join(path, key), message: "missing" });
    }
    for (const [key, item] of Object.entries(record)) {
      const prop = schema.properties?.[key];
      if (prop) errors.push(...check(prop, item, join(path, key), opts));
      else if (typeof schema.additionalProperties === "object") {
        errors.push(...check(schema.additionalProperties, item, join(path, key), opts));
      } else if (schema.additionalProperties === false && !opts.allowUnknownProperties) {
        errors.push({ path: join(path, key), message: "unknown property" });
      }
    }
  }
  return errors;
}

function join(path: string, key: string): string {
  return path ? `${path}.${key}` : key;
}

/** Validate a value against a named definition. Returns [] when valid. */
export function validate(
  defName: string,
  value: unknown,
  opts: ValidateOptions = { allowUnknownProperties: true },
): SchemaError[] {
  return check({ $ref: `#/$defs/${defName}` }, value, "", opts);
}

const envelope = defs.AgentResponse.properties as Record<string, Schema>;
const blockSchema = envelope.blocks.items as Schema;
const followUpSchema = envelope.follow_ups.items as Schema;
const placementSchema = (defs.Narrative.properties as Record<string, Schema>).placement;

/** Validate one hydrated block, so an invalid block renders BlockError instead of failing the
 * whole answer (§6 Step 3, §9). */
export function validateBlock(value: unknown, opts: ValidateOptions = { allowUnknownProperties: true }): SchemaError[] {
  return check(blockSchema, value, "", opts);
}

/** Validate one follow-up action; an invalid one is dropped, never shown (§6). */
export function validateFollowUp(
  value: unknown,
  opts: ValidateOptions = { allowUnknownProperties: true },
): SchemaError[] {
  return check(followUpSchema, value, "", opts);
}

/** Validate a block placement on its own, to keep an invalid block in its slot or tab. */
export function validatePlacement(value: unknown): SchemaError[] {
  return check(placementSchema, value, "", { allowUnknownProperties: false });
}
