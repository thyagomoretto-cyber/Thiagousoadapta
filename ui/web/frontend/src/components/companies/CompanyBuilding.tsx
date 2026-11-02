import { Component, Suspense, useEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from "react";
import { Canvas, useFrame, useThree, type ThreeEvent } from "@react-three/fiber";
import { Html, OrbitControls } from "@react-three/drei";
import { Group, Vector3 } from "three";
import type { OrbitControls as OrbitControlsInstance } from "three-stdlib";
import { ArrowLeft, Building2, ChevronRight, Maximize2, Minus, MousePointer2, Plus, RotateCcw, RotateCw, Send, X } from "lucide-react";
import { useReducedMotion } from "framer-motion";
import { cn } from "@/lib/utils";
import { buildOfficeLayout, type BuildingCompany, type BuildingMember, type OfficeRoom } from "./buildingLayout";

const STATUS = { livre: "Disponível", trabalhando: "A trabalhar", aguardando: "A aguardar", erro: "Precisa de atenção" };
const COLORS = { livre: "#8ba4bc", trabalhando: "#50e3ac", aguardando: "#f2c66d", erro: "#ff7c85" };
const FLOOR_HEIGHT = 3.5;
type Vec3 = [number, number, number];

function Box({ at, size, color, opacity = 1 }: { at: Vec3; size: Vec3; color: string; opacity?: number }) {
  return <mesh position={at} castShadow receiveShadow><boxGeometry args={size} /><meshStandardMaterial color={color} roughness={0.65} transparent={opacity < 1} opacity={opacity} depthWrite={opacity === 1} /></mesh>;
}

function Plant({ at }: { at: Vec3 }) {
  return <group position={at}><mesh position={[0, 0.22, 0]} castShadow><cylinderGeometry args={[0.22, 0.15, 0.44, 8]} /><meshStandardMaterial color="#e4ddd0" /></mesh>{[-0.18, 0, 0.18].map((x, i) => <mesh key={i} position={[x, 0.65 + i * 0.12, 0]} rotation={[0, 0, x * 2]} castShadow><sphereGeometry args={[0.26, 7, 6]} /><meshStandardMaterial color={i === 1 ? "#5e9878" : "#38785f"} /></mesh>)}</group>;
}

function Employee({ member, at, selected, onSelect, reducedMotion }: { member: BuildingMember; at: Vec3; selected: boolean; onSelect: () => void; reducedMotion: boolean }) {
  const hands = useRef<Group>(null);
  const working = member.status === "trabalhando";
  const manager = member.kind === "gerente";
  const accent = COLORS[member.status] ?? COLORS.livre;
  useFrame(({ clock }) => {
    if (hands.current) hands.current.rotation.x = working && !reducedMotion ? Math.sin(clock.elapsedTime * 7 + at[0]) * 0.09 : 0;
  });
  const click = (e: ThreeEvent<MouseEvent>) => { e.stopPropagation(); onSelect(); };
  return <group position={at} onClick={click}>
    <mesh position={[0, 0.04, 0]} rotation={[-Math.PI / 2, 0, 0]}><ringGeometry args={[0.5, selected ? 0.66 : 0.56, 28]} /><meshBasicMaterial color={selected ? "#ffffff" : accent} transparent opacity={selected ? 0.95 : 0.5} /></mesh>
    <Box at={[0, 0.78, -0.45]} size={[1.75, 0.12, 0.85]} color={manager ? "#b08c64" : "#cfb99c"} />
    {[-0.68, 0.68].map(x => <Box key={x} at={[x, 0.39, -0.45]} size={[0.08, 0.78, 0.65]} color="#39485a" />)}
    <Box at={[0, 1.18, -0.67]} size={[1.02, 0.59, 0.08]} color="#263548" />
    <mesh position={[0, 1.18, -0.618]}><planeGeometry args={[0.9, 0.46]} /><meshStandardMaterial color={working ? "#93e7df" : "#657a94"} emissive={working ? "#2c8c91" : "#172c42"} emissiveIntensity={0.6} /></mesh>
    <Box at={[0, 0.93, -0.66]} size={[0.06, 0.3, 0.06]} color="#263548" />
    <Box at={[0, 0.86, -0.66]} size={[0.4, 0.04, 0.24]} color="#263548" />
    <Box at={[0, 0.86, -0.22]} size={[0.67, 0.035, 0.23]} color="#e5e7e9" />
    <Box at={[0.62, 0.9, -0.28]} size={[0.14, 0.19, 0.14]} color="#eeeee5" />
    <Box at={[0, 0.43, 0.34]} size={[0.65, 0.12, 0.65]} color="#34465c" />
    <Box at={[0, 0.79, 0.62]} size={[0.65, 0.75, 0.1]} color="#34465c" />
    <Box at={[0, 0.23, 0.33]} size={[0.08, 0.4, 0.08]} color="#253346" />
    <Box at={[0, 0.1, 0.33]} size={[0.7, 0.07, 0.55]} color="#253346" />
    <group position={[0, 0.67, 0.25]}>
      <Box at={[0, 0.28, 0]} size={[0.48, 0.56, 0.3]} color={manager ? "#233954" : "#6486a0"} />
      {manager && <Box at={[0, 0.37, -0.16]} size={[0.08, 0.3, 0.02]} color="#e0b76b" />}
      <mesh position={[0, 0.76, -0.02]} castShadow><sphereGeometry args={[0.23, 12, 10]} /><meshStandardMaterial color="#d5ab89" /></mesh>
      <mesh position={[0, 0.89, 0.005]} castShadow><sphereGeometry args={[0.22, 10, 8, 0, Math.PI * 2, 0, Math.PI / 2]} /><meshStandardMaterial color={manager ? "#514539" : "#353d47"} /></mesh>
      <group ref={hands} position={[0, 0.35, -0.15]}>{[-0.29, 0.29].map(x => <group key={x}><Box at={[x, -0.03, -0.13]} size={[0.14, 0.14, 0.48]} color={manager ? "#233954" : "#6486a0"} /><mesh position={[x, -0.04, -0.4]}><sphereGeometry args={[0.085, 8, 6]} /><meshStandardMaterial color="#d5ab89" /></mesh></group>)}</group>
    </group>
    <mesh position={[0.48, 1.57, 0.25]}><sphereGeometry args={[0.08, 10, 8]} /><meshBasicMaterial color={accent} /></mesh>
    <Html position={[0, 1.94, 0.3]} center zIndexRange={[15, 0]}>
      <button type="button" onClick={(e) => { e.stopPropagation(); onSelect(); }} className={cn("max-w-40 whitespace-nowrap rounded-lg border px-2.5 py-1.5 text-left shadow-lg backdrop-blur-md transition-colors", selected ? "border-white/60 bg-slate-100 text-slate-950" : "border-white/15 bg-slate-950/85 text-white hover:border-teal-300/70")} aria-label={`Ver ${member.name}`}>
        <span className="block truncate text-[10px] font-semibold">{member.name}</span><span className="block text-[8px] opacity-70">{manager ? "Gerente" : member.kind === "especialista" ? "Especialista" : "Funcionário"} · {STATUS[member.status]}</span>
      </button>
    </Html>
  </group>;
}

function Room({ room, members, selected, selectedMember, onEnter, onSelect, reducedMotion }: { room: OfficeRoom; members: BuildingMember[]; selected: boolean; selectedMember: string | null; onEnter: () => void; onSelect: (id: string) => void; reducedMotion: boolean }) {
  return <group position={[room.x, 0, room.z]}>
    <mesh position={[0, 0.02, 0]} rotation={[-Math.PI / 2, 0, 0]} receiveShadow onClick={(e) => { e.stopPropagation(); onEnter(); }}><planeGeometry args={[room.width - 0.2, room.depth - 0.2]} /><meshStandardMaterial color={selected ? "#547a7d" : "#88949a"} roughness={0.9} /></mesh>
    <Box at={[-room.width / 2 + 0.07, 0.7, 0]} size={[0.1, 1.4, room.depth]} color="#b5c6ce" opacity={0.3} />
    <Box at={[0, 1, -room.depth / 2 + 0.06]} size={[room.width, 2, 0.12]} color="#d9ddd9" />
    <Box at={[0, 1.28, -room.depth / 2 + 0.14]} size={[room.width * 0.5, 0.65, 0.06]} color="#23485d" />
    <Html position={[0, 2.55, -room.depth / 2 + 0.15]} center zIndexRange={[14, 0]}><button type="button" onClick={onEnter} className="whitespace-nowrap rounded-full border border-white/20 bg-slate-900/90 px-3 py-1 text-[10px] font-semibold text-white shadow-lg hover:bg-teal-900">{room.department.name}<span className="ml-2 text-teal-200">↗</span></button></Html>
    <Plant at={[room.width / 2 - 0.55, 0, -room.depth / 2 + 0.6]} />
    <Box at={[room.width / 2 - 0.35, 0.5, room.depth / 2 - 0.6]} size={[0.45, 1, 1]} color="#566a76" />
    {members.map((member, index) => {
      const column = index % room.columns;
      const row = Math.floor(index / room.columns);
      const x = (column - (room.columns - 1) / 2) * 2.2;
      const z = -room.depth / 2 + 2.4 + row * 2.65;
      return <Employee key={member.id} member={member} at={[x, 0, z]} selected={selectedMember === member.id} onSelect={() => onSelect(member.id)} reducedMotion={reducedMotion} />;
    })}
    {!members.length && <Html position={[0, 0.8, 0]} center><span className="whitespace-nowrap rounded-lg bg-slate-900/80 px-3 py-2 text-xs text-slate-300">Sala disponível</span></Html>}
  </group>;
}

function CameraRig({ controls, center, distance, viewKey, spinning, reducedMotion }: { controls: RefObject<OrbitControlsInstance>; center: Vec3; distance: number; viewKey: string; spinning: boolean; reducedMotion: boolean }) {
  const { camera } = useThree();
  const goal = useRef<{ position: Vector3; target: Vector3 } | null>(null);
  useEffect(() => {
    const target = new Vector3(...center);
    const position = target.clone().add(new Vector3(distance * 0.8, distance * 0.65, distance));
    if (reducedMotion) { camera.position.copy(position); controls.current?.target.copy(target); controls.current?.update(); }
    else goal.current = { position, target };
    // The key represents an explicit navigation action; live status changes do not reset the camera.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewKey, reducedMotion]);
  useFrame((_, dt) => {
    if (!goal.current || !controls.current) return;
    const amount = 1 - Math.exp(-dt * 5);
    camera.position.lerp(goal.current.position, amount);
    controls.current.target.lerp(goal.current.target, amount);
    controls.current.update();
    if (camera.position.distanceTo(goal.current.position) < 0.02) goal.current = null;
  });
  return <OrbitControls ref={controls} makeDefault enableDamping dampingFactor={0.09} minDistance={2.4} maxDistance={Math.max(65, distance * 4)} minPolarAngle={0.15} maxPolarAngle={Math.PI / 2 - 0.035} autoRotate={spinning && !reducedMotion} autoRotateSpeed={0.6} onStart={() => { goal.current = null; }} />;
}

class SceneBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    if (this.state.failed) return <div className="absolute inset-0 grid place-items-center p-10 text-center text-slate-300"><p>A vista 3D não está disponível neste dispositivo. Pode selecionar os andares e as pessoas no painel ao lado.</p></div>;
    return this.props.children;
  }
}

export function CompanyBuilding({ company, delegate }: { company: BuildingCompany; delegate: (member: BuildingMember) => void }) {
  const layout = useMemo(() => buildOfficeLayout(company), [company]);
  const [floor, setFloor] = useState<number | null>(null);
  const [roomId, setRoomId] = useState<string | null>(null);
  const [memberId, setMemberId] = useState<string | null>(null);
  const [spinning, setSpinning] = useState(false);
  const [reset, setReset] = useState(0);
  const controls = useRef<OrbitControlsInstance>(null);
  const host = useRef<HTMLDivElement>(null);
  const reducedMotion = !!useReducedMotion();
  const member = company.members.find(m => m.id === memberId);
  const selectedRoom = layout.rooms.find(r => r.department.id === (member?.departmentId ?? roomId));
  const floorRooms = floor === null ? layout.rooms : layout.rooms.filter(r => r.floor === floor);
  const visibleMembers = floor === null ? company.members : company.members.filter(m => floorRooms.some(r => r.department.id === m.departmentId));
  const fullHeight = layout.floors.length * FLOOR_HEIGHT;
  const center: Vec3 = selectedRoom ? [selectedRoom.x, 0.9, selectedRoom.z] : [0, floor === null ? fullHeight * 0.42 : 0.8, 0];
  const distance = member ? 4 : selectedRoom ? Math.max(selectedRoom.width, selectedRoom.depth) * 0.85 : floor === null ? Math.max(layout.width, fullHeight, layout.depth) * 1.6 : Math.max(layout.width, layout.depth) * 0.95;
  useEffect(() => { setFloor(null); setRoomId(null); setMemberId(null); setSpinning(false); }, [company.id]);
  const outside = () => { setFloor(null); setRoomId(null); setMemberId(null); setReset(n => n + 1); };
  const enterFloor = (value: number) => { setFloor(value); setRoomId(null); setMemberId(null); };
  const selectMember = (id: string) => {
    const person = company.members.find(m => m.id === id);
    const room = layout.rooms.find(r => r.department.id === person?.departmentId);
    if (room) { setFloor(room.floor); setRoomId(room.department.id); }
    setMemberId(id);
  };
  const zoom = (factor: number) => {
    const c = controls.current;
    if (!c) return;
    const offset = c.object.position.clone().sub(c.target);
    const next = Math.max(c.minDistance, Math.min(c.maxDistance, offset.length() * factor));
    c.object.position.copy(c.target.clone().add(offset.setLength(next)));
    c.update();
  };
  const fullscreen = () => {
    if (document.fullscreenElement) void document.exitFullscreen().catch(() => {});
    else void host.current?.requestFullscreen?.().catch(() => {});
  };
  return <div ref={host} className="relative flex min-h-[650px] h-[calc(100dvh-190px)] flex-col overflow-hidden rounded-2xl border border-slate-700 bg-[#101c2b] text-slate-100" data-testid="company-building-3d">
    <div className="z-20 flex flex-wrap items-center justify-between gap-3 border-b border-white/10 bg-[#142133]/95 px-5 py-3">
      <div><div className="text-[10px] uppercase tracking-[0.25em] text-teal-300">Escritório vivo</div><div className="mt-1 flex items-center gap-2 text-sm"><button type="button" onClick={outside} className="font-semibold hover:text-teal-200">{company.name}</button>{floor !== null && <><ChevronRight className="h-3 w-3 text-slate-500" /><button type="button" onClick={() => enterFloor(floor)}>{floor}º andar</button></>}{selectedRoom && <><ChevronRight className="h-3 w-3 text-slate-500" /><span className="truncate text-teal-200">{selectedRoom.department.name}</span></>}</div></div>
      <div className="flex items-center gap-1">{floor !== null && <button type="button" onClick={outside} className="mr-2 flex items-center gap-2 rounded-lg bg-white/10 px-3 py-2 text-xs hover:bg-white/20"><ArrowLeft className="h-3.5 w-3.5" />Sair do andar</button>}<button type="button" aria-label="Reduzir zoom" title="Reduzir zoom" onClick={() => zoom(1.25)} className="rounded-lg p-2 hover:bg-white/10"><Minus className="h-4 w-4" /></button><button type="button" aria-label="Aumentar zoom" title="Aumentar zoom" onClick={() => zoom(0.8)} className="rounded-lg p-2 hover:bg-white/10"><Plus className="h-4 w-4" /></button><button type="button" aria-label="Rodar o prédio" aria-pressed={spinning} title="Rotação automática" onClick={() => setSpinning(v => !v)} className={cn("rounded-lg p-2 hover:bg-white/10", spinning && "bg-teal-300/20 text-teal-200")}><RotateCw className="h-4 w-4" /></button><button type="button" aria-label="Repor vista" title="Repor vista" onClick={outside} className="rounded-lg p-2 hover:bg-white/10"><RotateCcw className="h-4 w-4" /></button><button type="button" aria-label="Ecrã inteiro" title="Ecrã inteiro" onClick={fullscreen} className="rounded-lg p-2 hover:bg-white/10"><Maximize2 className="h-4 w-4" /></button></div>
    </div>
    <div className="relative min-h-0 flex-1">
      <SceneBoundary><Suspense fallback={<div className="absolute inset-0 grid place-items-center text-sm text-teal-100">A preparar o escritório…</div>}><Canvas shadows dpr={[1, 1.6]} camera={{ position: [18, 16, 24], fov: 42, near: 0.1, far: 2000 }} fallback={<div className="p-10 text-sm">A vista 3D precisa de WebGL. Use o painel para aceder à equipa.</div>}>
        <color attach="background" args={["#101c2b"]} />
        <ambientLight intensity={1.1} /><hemisphereLight args={["#d7efff", "#718072", 1.6]} /><directionalLight position={[12, 25, 15]} intensity={2.6} castShadow shadow-mapSize={[2048, 2048]} shadow-camera-left={-30} shadow-camera-right={30} shadow-camera-top={35} shadow-camera-bottom={-30} shadow-camera-far={100} shadow-bias={-0.001} />
        <mesh position={[0, -0.55, 0]} rotation={[-Math.PI / 2, 0, 0]} receiveShadow><planeGeometry args={[300, 300]} /><meshStandardMaterial color="#192a3d" roughness={1} /></mesh>
        <gridHelper args={[100, 50, "#2d4357", "#213548"]} position={[0, -0.53, 0]} />
        <Box at={[0, -0.25, 0]} size={[layout.width + 1.4, 0.5, layout.depth + 1.4]} color="#52677b" />
        {layout.floors.filter(f => floor === null || f === floor).map((f, index) => {
          const y = floor === null ? index * FLOOR_HEIGHT : 0;
          return <group key={f} position={[0, y, 0]}>
            <Box at={[0, -0.06, 0]} size={[layout.width + 0.3, 0.23, layout.depth + 0.3]} color="#d6d9d4" />
            <Box at={[0, -0.15, layout.depth / 2 + 0.15]} size={[layout.width + 0.4, 0.16, 0.18]} color="#4dbaa9" />
            {[-1, 1].flatMap(x => [-1, 1].map(z => <Box key={`${x}-${z}`} at={[x * (layout.width / 2 + 0.05), 1.6, z * (layout.depth / 2 + 0.05)]} size={[0.18, 3.3, 0.18]} color="#5d778a" />))}
            <Box at={[layout.width / 2 + 0.03, 1.5, 0]} size={[0.04, 2.7, layout.depth]} color="#a4d4dc" opacity={0.1} />
            <Html position={[-layout.width / 2 - 0.35, 0.8, layout.depth / 2]} center zIndexRange={[12, 0]}><button type="button" aria-label={`Entrar no ${f}º andar`} onClick={() => enterFloor(f)} className="whitespace-nowrap rounded-xl border border-teal-200/30 bg-slate-900/90 px-3 py-2 text-xs text-teal-100 shadow-xl hover:bg-teal-900">{f}º andar <span className="ml-2">↗</span></button></Html>
            {layout.rooms.filter(r => r.floor === f).map(room => <Room key={room.department.id} room={room} members={company.members.filter(m => m.departmentId === room.department.id)} selected={roomId === room.department.id} selectedMember={memberId} onEnter={() => { setFloor(f); setRoomId(room.department.id); setMemberId(null); }} onSelect={selectMember} reducedMotion={reducedMotion} />)}
          </group>;
        })}
        {floor === null && <group><Box at={[0, fullHeight - 0.12, 0]} size={[layout.width + 0.65, 0.3, layout.depth + 0.65]} color="#40576a" /><Box at={[0, fullHeight + 0.25, -layout.depth / 2 + 0.8]} size={[layout.width * 0.65, 0.5, 1]} color="#344b60" /><Html position={[0, fullHeight + 0.65, 0]} center zIndexRange={[12, 0]}><div className="whitespace-nowrap rounded-xl border border-white/20 bg-slate-900/90 px-5 py-2 text-sm font-semibold tracking-wide text-white shadow-xl">{company.name}</div></Html></group>}
        <CameraRig controls={controls} center={center} distance={distance} viewKey={`${company.id}/${floor}/${roomId}/${memberId}/${reset}`} spinning={spinning} reducedMotion={reducedMotion} />
      </Canvas></Suspense></SceneBoundary>
      <div className="absolute left-4 top-4 z-20 max-w-[145px] rounded-xl border border-white/10 bg-slate-950/80 p-3 shadow-xl backdrop-blur-xl"><div className="mb-2 flex items-center gap-2 text-[10px] uppercase tracking-wider text-slate-400"><Building2 className="h-3 w-3" />Elevador</div><div className="flex max-h-60 flex-col gap-1 overflow-y-auto"><button type="button" onClick={outside} className={cn("rounded-lg px-3 py-2 text-left text-xs hover:bg-white/10", floor === null && "bg-teal-300/15 text-teal-200")}>Prédio completo</button>{[...layout.floors].reverse().map(f => <button key={f} type="button" onClick={() => enterFloor(f)} className={cn("rounded-lg px-3 py-2 text-left text-xs hover:bg-white/10", floor === f && "bg-teal-300/15 text-teal-200")}>{f}º andar</button>)}</div></div>
      <div className="absolute bottom-4 left-4 z-20 hidden rounded-xl border border-white/10 bg-slate-950/80 px-3 py-2 text-[10px] text-slate-300 backdrop-blur-md sm:block"><MousePointer2 className="mr-1.5 inline h-3 w-3 text-teal-300" />Arraste para rodar · Roda para zoom · Clique numa sala ou pessoa</div>
      <aside className="absolute bottom-4 right-4 top-4 z-20 flex w-60 flex-col overflow-hidden rounded-xl border border-white/10 bg-slate-950/90 shadow-xl backdrop-blur-xl max-[1000px]:top-auto max-[1000px]:max-h-[42%]" aria-label="Equipa do prédio">
        {member ? <><div className="flex items-center justify-between border-b border-white/10 px-4 py-3"><span className="text-[10px] uppercase tracking-widest text-teal-300">Pessoa selecionada</span><button type="button" aria-label="Fechar pessoa" onClick={() => setMemberId(null)} className="rounded p-1 hover:bg-white/10"><X className="h-3.5 w-3.5" /></button></div><div className="min-h-0 flex-1 overflow-y-auto p-4"><h3 className="text-base font-semibold">{member.name}</h3><p className="mt-1 text-xs text-slate-400">{member.role}</p><div className="mt-4 flex items-center gap-2 text-xs"><span className="h-2 w-2 rounded-full" style={{ backgroundColor: COLORS[member.status] }} />{STATUS[member.status]}</div><p className="mt-3 text-[10px] text-slate-400">Estado registado na empresa</p><div className="mt-4 rounded-lg border border-white/10 bg-white/5 p-3 text-xs leading-relaxed">{member.currentTask || "Sem tarefa ativa registada."}</div><button type="button" onClick={() => delegate(member)} className="mt-4 flex w-full items-center justify-center gap-2 rounded-lg bg-teal-300 px-3 py-2.5 text-xs font-semibold text-slate-950 hover:bg-teal-200"><Send className="h-3.5 w-3.5" />Delegar tarefa</button></div></> : <><div className="border-b border-white/10 px-4 py-3"><div className="text-[10px] uppercase tracking-widest text-teal-300">{floor === null ? "Dentro do prédio" : `${floor}º andar`}</div><p className="mt-1 text-xs text-slate-400">{visibleMembers.filter(m => m.status === "trabalhando").length} a trabalhar · {visibleMembers.length} pessoas</p></div><div className="min-h-0 flex-1 overflow-y-auto p-2">{visibleMembers.map(m => <button key={m.id} type="button" onClick={() => selectMember(m.id)} className="mb-1 flex w-full items-center gap-3 rounded-lg px-2 py-3 text-left hover:bg-white/10"><span className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: COLORS[m.status] }} /><span className="min-w-0"><span className="block truncate text-xs font-medium">{m.name}</span><span className="block truncate text-[10px] text-slate-400">{m.role}</span></span><ChevronRight className="ml-auto h-3 w-3 shrink-0 text-slate-500" /></button>)}{!visibleMembers.length && <p className="p-3 text-xs leading-relaxed text-slate-400">Ainda não há pessoas neste andar. Adicione-as na aba Equipa.</p>}</div></>}
      </aside>
      {!layout.floors.length && <div className="absolute inset-x-40 top-1/2 text-center text-sm text-slate-300">Adicione um departamento para abrir o primeiro andar.</div>}
    </div>
  </div>;
}
