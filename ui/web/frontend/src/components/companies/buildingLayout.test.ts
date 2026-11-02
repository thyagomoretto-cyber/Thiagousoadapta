import { describe, expect, it } from "vitest";
import { buildOfficeLayout, type BuildingCompany, type BuildingMember } from "./buildingLayout";

const person = (id: string, departmentId: string): BuildingMember => ({ id, name: id, role: "Specialist", departmentId, kind: "funcionario", status: "livre", model: "JARVIS", autonomy: "assistido" });
const department = (id: string, floor: number) => ({ id, name: id, floor, mission: "" });
function company(departments: BuildingCompany["departments"], members: BuildingMember[] = []): BuildingCompany {
  return { id: "example", name: "Example", departments, members };
}
describe("office layout", () => {
  it("groups departments on their real floors, including shared and non-consecutive floors", () => {
    const layout = buildOfficeLayout(company([department("a", 8), department("b", 2), department("c", 8)]));
    expect(layout.floors).toEqual([2, 8]);
    expect(layout.rooms.filter(r => r.floor === 8)).toHaveLength(2);
    expect(layout.rooms.map(r => r.department.id).sort()).toEqual(["a", "b", "c"]);
  });
  it("gives every department a separate non-overlapping room inside the footprint", () => {
    const layout = buildOfficeLayout(company(Array.from({ length: 7 }, (_, i) => department(`d${i}`, 1))));
    for (const room of layout.rooms) {
      expect(Math.abs(room.x) + room.width / 2).toBeLessThanOrEqual(layout.width / 2);
      expect(Math.abs(room.z) + room.depth / 2).toBeLessThanOrEqual(layout.depth / 2);
      for (const other of layout.rooms.filter(r => r !== room)) {
        expect(Math.abs(room.x - other.x) >= room.width || Math.abs(room.z - other.z) >= room.depth).toBe(true);
      }
    }
  });
  it("expands the office so a large team has space for every desk", () => {
    const layout = buildOfficeLayout(company([department("a", 1)], Array.from({ length: 35 }, (_, i) => person(`${i}`, "a"))));
    const room = layout.rooms[0];
    for (let i = 0; i < 35; i++) {
      const x = (i % room.columns - (room.columns - 1) / 2) * 2.2;
      const z = -room.depth / 2 + 2.4 + Math.floor(i / room.columns) * 2.65;
      expect(Math.abs(x) + 0.9).toBeLessThan(room.width / 2);
      expect(z + 0.7).toBeLessThan(room.depth / 2);
    }
  });
  it("does not invent departments or employees for an empty company", () => {
    const layout = buildOfficeLayout(company([]));
    expect(layout.rooms).toEqual([]);
    expect(layout.floors).toEqual([]);
    expect(layout.width).toBeGreaterThan(0);
    expect(layout.depth).toBeGreaterThan(0);
  });
});
