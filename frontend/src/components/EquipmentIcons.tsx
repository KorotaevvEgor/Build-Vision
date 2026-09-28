/**
 * Премиальные (не эмодзи) иконки техники — плоские дуотон-иконки от руки,
 * без внешних ассетов и npm-зависимостей. Цвет берётся из currentColor,
 * поэтому карточка сама красит иконку через CSS `color`.
 */
import type { ComponentType, SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement>;

function Base({ children, ...rest }: IconProps) {
  return (
    <svg
      viewBox="0 0 40 40"
      width="1em"
      height="1em"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      {...rest}
    >
      {children}
    </svg>
  );
}

function Excavator(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M4 30h16v3H4z" fill="currentColor" opacity=".22" />
      <path d="M5 30h14M6 33h12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      <circle cx="8.5" cy="30" r="2.6" fill="currentColor" opacity=".35" />
      <circle cx="16.5" cy="30" r="2.6" fill="currentColor" opacity=".35" />
      <path d="M7 26h13l3-6H10Z" fill="currentColor" opacity=".22" />
      <path d="M7 26h13l3-6H10Z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
      <rect x="12" y="15" width="8" height="6" rx="1.4" stroke="currentColor" strokeWidth="1.6" />
      <path d="M20 17 30 12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      <path d="M30 12 35 20" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      <path d="M35 20 31 25 26 23Z" fill="currentColor" opacity=".35" />
      <path d="M35 20 31 25 26 23Z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
    </Base>
  );
}

function DumpTruck(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M3 27h4.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      <rect x="4" y="17" width="9" height="10" rx="1.2" stroke="currentColor" strokeWidth="1.6" />
      <path d="M6 20h5v4H6z" fill="currentColor" opacity=".3" />
      <path d="M13 22h8l4 5H13Z" fill="currentColor" opacity=".22" />
      <path d="M13 15h20l3 7H13Z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
      <path d="M13 15h20l3 7H13Z" fill="currentColor" opacity=".12" />
      <path d="M4 27h32" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      <circle cx="11" cy="30" r="3" stroke="currentColor" strokeWidth="1.8" fill="currentColor" fillOpacity=".18" />
      <circle cx="30" cy="30" r="3" stroke="currentColor" strokeWidth="1.8" fill="currentColor" fillOpacity=".18" />
    </Base>
  );
}

function MobileCrane(props: IconProps) {
  return (
    <Base {...props}>
      <rect x="4" y="22" width="12" height="7" rx="1.2" stroke="currentColor" strokeWidth="1.6" />
      <rect x="6" y="24" width="4" height="3" fill="currentColor" opacity=".3" />
      <circle cx="8" cy="31" r="2.4" fill="currentColor" opacity=".35" />
      <circle cx="14" cy="31" r="2.4" fill="currentColor" opacity=".35" />
      <path d="M12 22 30 6" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
      <path d="M12 22 4 22" stroke="currentColor" strokeWidth="1.6" />
      <path d="M30 6 33 20" stroke="currentColor" strokeWidth="1.4" strokeDasharray="2 2" />
      <circle cx="33" cy="22" r="1.6" fill="currentColor" />
      <path d="M9 22v-4l3-1" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
    </Base>
  );
}

function CraneManipulator(props: IconProps) {
  return (
    <Base {...props}>
      <rect x="4" y="21" width="13" height="8" rx="1.2" stroke="currentColor" strokeWidth="1.6" />
      <circle cx="8" cy="31" r="2.4" fill="currentColor" opacity=".35" />
      <circle cx="15" cy="31" r="2.4" fill="currentColor" opacity=".35" />
      <path d="M13 21 22 10 30 14" stroke="currentColor" strokeWidth="2.1" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M30 14 34 22" stroke="currentColor" strokeWidth="2.1" strokeLinecap="round" />
      <path d="M34 22 30 26 26 24Z" fill="currentColor" opacity=".35" />
      <path d="M34 22 30 26 26 24Z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
    </Base>
  );
}

function ConcreteMixer(props: IconProps) {
  return (
    <Base {...props}>
      <rect x="4" y="20" width="10" height="9" rx="1.2" stroke="currentColor" strokeWidth="1.6" />
      <circle cx="8" cy="31" r="2.4" fill="currentColor" opacity=".35" />
      <circle cx="27" cy="31" r="2.4" fill="currentColor" opacity=".35" />
      <path d="M14 22h5l3 7h-8z" fill="currentColor" opacity=".18" />
      <ellipse cx="24" cy="18" rx="9" ry="6.4" stroke="currentColor" strokeWidth="1.6" transform="rotate(-18 24 18)" />
      <path
        d="M18.5 15.5c2 1.5 5 1.5 7 0M17.5 19c2.5 1.7 6.5 1.7 9 0"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinecap="round"
        opacity=".8"
      />
      <path d="M23 24 21 29h10l-2-6" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
    </Base>
  );
}

function Bulldozer(props: IconProps) {
  return (
    <Base {...props}>
      <rect x="9" y="27" width="22" height="3.4" rx="1.7" fill="currentColor" opacity=".3" />
      <rect x="9" y="27" width="22" height="3.4" rx="1.7" stroke="currentColor" strokeWidth="1.4" />
      <rect x="15" y="17" width="12" height="7" rx="1.2" stroke="currentColor" strokeWidth="1.6" />
      <path d="M18 19h5v3h-5z" fill="currentColor" opacity=".3" />
      <path d="M15 21H8.5c-1.4 0-2.5 1-2.5 2.4V27" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
      <path d="M4 20v9" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
      <path d="M27 22h4l2 5h-6z" fill="currentColor" opacity=".22" />
    </Base>
  );
}

function RoadRoller(props: IconProps) {
  return (
    <Base {...props}>
      <circle cx="10" cy="27" r="6" stroke="currentColor" strokeWidth="1.8" fill="currentColor" fillOpacity=".16" />
      <circle cx="29" cy="27" r="4.6" stroke="currentColor" strokeWidth="1.8" fill="currentColor" fillOpacity=".16" />
      <path d="M13 22h13v9H16" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
      <rect x="16" y="13" width="8" height="7" rx="1.2" stroke="currentColor" strokeWidth="1.6" />
      <path d="M18 15h4v3h-4z" fill="currentColor" opacity=".3" />
    </Base>
  );
}

function Truck(props: IconProps) {
  return (
    <Base {...props}>
      <rect x="4" y="16" width="16" height="11" rx="1.2" stroke="currentColor" strokeWidth="1.6" />
      <path d="M6 19h12v5H6z" fill="currentColor" opacity=".16" />
      <path d="M20 20h7l5 4v3h-12z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
      <path d="M20 20h7l5 4v3h-12z" fill="currentColor" opacity=".12" />
      <circle cx="11" cy="30" r="3" stroke="currentColor" strokeWidth="1.8" fill="currentColor" fillOpacity=".18" />
      <circle cx="27" cy="30" r="3" stroke="currentColor" strokeWidth="1.8" fill="currentColor" fillOpacity=".18" />
    </Base>
  );
}

function GenericMachine(props: IconProps) {
  return (
    <Base {...props}>
      <rect x="8" y="12" width="24" height="16" rx="2.4" stroke="currentColor" strokeWidth="1.7" />
      <path d="M8 20h24" stroke="currentColor" strokeWidth="1.4" opacity=".6" />
      <circle cx="14" cy="24" r="1.6" fill="currentColor" />
      <circle cx="20" cy="24" r="1.6" fill="currentColor" />
      <circle cx="26" cy="24" r="1.6" fill="currentColor" />
      <path d="M14 30v3M26 30v3" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </Base>
  );
}

const ICONS: Record<string, ComponentType<IconProps>> = {
  excavator: Excavator,
  dump_truck: DumpTruck,
  mobile_crane: MobileCrane,
  crane_manipulator: CraneManipulator,
  concrete_mixer: ConcreteMixer,
  bulldozer: Bulldozer,
  road_roller: RoadRoller,
  truck: Truck,
};

export function EquipmentIcon({ classKey, ...rest }: { classKey: string } & IconProps) {
  const Icon = ICONS[classKey] ?? GenericMachine;
  return <Icon {...rest} />;
}
