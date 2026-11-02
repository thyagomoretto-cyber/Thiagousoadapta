/** Physical office layout derived only from the company's real roster. */
export interface BuildingMember {
  id: string; name: string; role: string; departmentId: string;
  kind: "gerente" | "especialista" | "funcionario";
  status: "livre" | "trabalhando" | "aguardando" | "erro";
  model: string; autonomy: "assistido" | "semi-autonomo" | "autonomo";
  currentTask?: string | null;
}
export interface BuildingDepartment { id: string; name: string; floor: number; mission: string }
export interface BuildingCompany { id: string; name: string; departments: BuildingDepartment[]; members: BuildingMember[] }
export interface OfficeRoom { department: BuildingDepartment; floor: number; x: number; z: number; width: number; depth: number; columns: number }
export function buildOfficeLayout(company: BuildingCompany) {
  const floors = [...new Set(company.departments.map(d => d.floor))].sort((a, b) => a - b);
  const perFloor = Math.max(1, ...floors.map(f => company.departments.filter(d => d.floor === f).length));
  const roomColumns = Math.min(3, perFloor);
  const staffCounts = company.departments.map(d => company.members.filter(m => m.departmentId === d.id).length);
  const staffColumns = Math.min(3, Math.max(1, ...staffCounts));
  const roomWidth = Math.max(6, staffColumns * 2.2 + 1.6);
  const roomDepth = Math.max(7, Math.ceil(Math.max(1, ...staffCounts) / staffColumns) * 2.65 + 3);
  const width = Math.max(10, roomColumns * roomWidth);
  const depth = Math.ceil(perFloor / roomColumns) * roomDepth;
  const rooms: OfficeRoom[] = [];
  for (const floor of floors) {
    const departments = company.departments.filter(d => d.floor === floor);
    departments.forEach((department, index) => {
      const cols = Math.min(roomColumns, departments.length);
      const col = index % roomColumns;
      const row = Math.floor(index / roomColumns);
      rooms.push({ department, floor, x: (col - (cols - 1) / 2) * roomWidth, z: -depth / 2 + roomDepth / 2 + row * roomDepth, width: roomWidth, depth: roomDepth, columns: staffColumns });
    });
  }
  return { floors, rooms, width, depth };
}
