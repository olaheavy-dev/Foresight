
import { THEME_INIT_SCRIPT as INIT_SCRIPT_FOR_KEY_CHECK, THEME_KEY as KEY_FOR_CHECK } from "./theme";
import { expect as expectKey, test as testKey } from "vitest";

testKey("the init script reads the same storage key as THEME_KEY", () => {
  expectKey(INIT_SCRIPT_FOR_KEY_CHECK).toContain(`var k="${KEY_FOR_CHECK}"`);
});
