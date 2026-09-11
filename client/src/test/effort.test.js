import { toHours, describeHours, HOURS_PER_MONTH } from "../utils/effort.js";

// Effort is stored in hours because the math wants hours; it is entered in whatever a person
// estimates in. The basis is a working calendar, not the wall clock.

describe("effort units", () => {
  it("converts on the working calendar", () => {
    expect(toHours("2", "hours")).toBe(2);
    expect(toHours("1", "days")).toBe(8);
    expect(toHours("1", "weeks")).toBe(40);
    expect(toHours("1", "months")).toBe(173.33);
    expect(toHours("5", "weeks")).toBe(200);
  });

  it("is NaN for nothing, not zero — zero would silently pass as an estimate", () => {
    expect(toHours("", "days")).toBeNaN();
    expect(toHours("abc", "weeks")).toBeNaN();
  });

  it("reads back in the largest unit that is whole-ish, and stays in hours under a day", () => {
    expect(describeHours(3)).toBe("3h");
    expect(describeHours(1.5)).toBe("1.5h");
    expect(describeHours(8)).toBe("1 d");
    expect(describeHours(12)).toBe("1.5 d");
    expect(describeHours(40)).toBe("1 wk");
    expect(describeHours(200)).toBe("1.2 mo");
    expect(describeHours(HOURS_PER_MONTH * 3)).toBe("3 mo");
    expect(describeHours(0)).toBeNull();
    expect(describeHours(undefined)).toBeNull();
  });
});
