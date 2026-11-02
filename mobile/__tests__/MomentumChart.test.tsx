import { render, screen } from "@testing-library/react-native";

import { chartGeometry, MomentumChart } from "../src/components/MomentumChart";
import { shift } from "./fixtures";

const points = [
  { period: 1, minute: 0, net: 0 },
  { period: 1, minute: 5, net: 0.05 },
  { period: 1, minute: 9, net: -0.2 },
];

test("geometry clamps values and places shift markers by minute", () => {
  const { area, markers } = chartGeometry(points, [shift], 101);
  expect(area.startsWith("M 0 60")).toBe(true);
  expect(area).toContain("L 288.0 114.0"); // -0.2 is clamped to the -0.1 floor.
  expect(markers).toEqual([{ id: "shift-1", x: 384, home: true }]);
});

test("renders the area and one marker per shift", async () => {
  await render(<MomentumChart points={points} shifts={[shift]} homeId={101} />);
  expect(screen.getByTestId("momentum-area")).toBeTruthy();
  expect(screen.getByTestId("shift-marker-shift-1")).toBeTruthy();
});

test("shows a waiting message before any data", async () => {
  await render(<MomentumChart points={[]} shifts={[]} homeId={101} />);
  expect(screen.getByText("Waiting for the first actions…")).toBeTruthy();
});
