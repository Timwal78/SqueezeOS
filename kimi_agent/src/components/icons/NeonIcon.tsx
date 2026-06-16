interface NeonIconProps {
  type: "satellite" | "radar" | "broadcast" | "shield" | "agent" | "transaction" | "target" | "interceptor";
  color?: string;
  size?: number;
  active?: boolean;
}

export default function NeonIcon({ type, color = "#00E5FF", size = 24, active = false }: NeonIconProps) {
  const dimensions = size * 1.5;
  const half = dimensions / 2;

  const paths: Record<string, string> = {
    satellite: `M${half},10 L${half},${dimensions - 10} M${half - 10},${half} L${half + 10},${half} M${half},10 L${half - 5},5 M${half},10 L${half + 5},5 M${half},${dimensions - 10} L${half - 5},${dimensions - 5} M${half},${dimensions - 10} L${half + 5},${dimensions - 5}`,
    radar: `M${half},${half} m-10,0 a10,10 0 1,0 20,0 a10,10 0 1,0 -20,0 M${half},${half} L${half},${half - 15}`,
    broadcast: `M${half},${half - 5} L${half},${half + 5} M${half - 5},${half} A5,5 0 1,0 ${half + 5},${half} M${half - 10},${half} A10,10 0 1,0 ${half + 10},${half}`,
    shield: `M${half},8 L${dimensions - 8},14 L${dimensions - 8},${half} Q${dimensions - 8},${dimensions - 12} ${half},${dimensions - 8} Q8,${dimensions - 12} 8,${half} L8,14 Z`,
    agent: `M${half},10 Q${half + 12},${half - 5} ${half},${half} Q${half - 12},${half + 5} ${half},${dimensions - 10} M${half - 8},${half - 4} L${half + 8},${half + 4}`,
    transaction: `M${half - 8},${half - 6} L${half + 4},${half - 6} L${half + 4},${half - 10} L${half + 12},${half - 2} L${half + 4},${half + 6} L${half + 4},${half + 2} L${half - 8},${half + 2} Z M${half + 4},${half + 8} L${half - 4},${half + 8} L${half - 4},${half + 12} L${half - 12},${half + 4} L${half - 4},${half - 4} L${half - 4},${half} L${half + 4},${half} Z`,
    target: `M${half},${half} m-12,0 a12,12 0 1,0 24,0 a12,12 0 1,0 -24,0 M${half},${half} m-6,0 a6,6 0 1,0 12,0 a6,6 0 1,0 -12,0 M${half},4 L${half},10 M${half},${dimensions - 10} L${half},${dimensions - 4} M4,${half} L10,${half} M${dimensions - 10},${half} L${dimensions - 4},${half}`,
    interceptor: `M${half},6 L${half + 8},14 L${half + 8},${dimensions - 10} L${half},${dimensions - 6} L${half - 8},${dimensions - 10} L${half - 8},14 Z M${half},${half - 4} L${half},${half + 6} M${half - 4},${half + 2} L${half + 4},${half + 2}`,
  };

  return (
    <svg
      width={dimensions}
      height={dimensions}
      viewBox={`0 0 ${dimensions} ${dimensions}`}
      className="overflow-visible flex-shrink-0"
    >
      <path
        d={paths[type] || paths.satellite}
        fill="none"
        stroke={color}
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d={paths[type] || paths.satellite}
        className="transition-opacity duration-500"
        style={{ opacity: active ? 1 : 0, stroke: color, strokeWidth: 4, filter: "blur(4px)" }}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
