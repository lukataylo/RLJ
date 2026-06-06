// Crisp inline vehicle glyphs for the active-delivery cards. Stroke uses
// currentColor so the icon inherits the courier-status / accent colour around it.

import type { CourierVehicle } from "../types";

interface IconProps {
  size?: number;
  className?: string;
}

/** Box van — for "van" couriers. */
export function VanIcon({ size = 22, className }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden
    >
      <path d="M2 6.5h11v8.5H2z" />
      <path d="M13 9h4.2l3 3.3V15H13z" />
      <circle cx="6.2" cy="17" r="1.7" />
      <circle cx="16.8" cy="17" r="1.7" />
      <path d="M7.9 17h7.2M2 17h2.5M18.5 17H21" />
    </svg>
  );
}

/** Moped / scooter — for "scooter" couriers. */
export function ScooterIcon({ size = 22, className }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden
    >
      <circle cx="5" cy="17.5" r="2.6" />
      <circle cx="18.5" cy="17.5" r="2.6" />
      <path d="M7.5 17.5h6.7l3-7.2H14" />
      <path d="M14 10.3l1.4-3.8H18" />
      <path d="M14.2 17.5c.4-3 1.9-4.6 4.3-4.8" />
    </svg>
  );
}

/** Pedal bike — for "bike" couriers. */
export function BikeIcon({ size = 22, className }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden
    >
      <circle cx="5.5" cy="17" r="3.2" />
      <circle cx="18.5" cy="17" r="3.2" />
      <path d="M5.5 17l3.7-7h5.1" />
      <path d="M9.2 10l5 7M14.3 7h2.4l1.8 10" />
      <circle cx="9.2" cy="10" r="0.4" />
    </svg>
  );
}

/** Pick the right vehicle glyph for a courier's vehicle_type (defaults to van). */
export function VehicleIcon({
  vehicle,
  size,
  className,
}: {
  vehicle: CourierVehicle | undefined;
  size?: number;
  className?: string;
}) {
  if (vehicle === "scooter") return <ScooterIcon size={size} className={className} />;
  if (vehicle === "bike") return <BikeIcon size={size} className={className} />;
  return <VanIcon size={size} className={className} />;
}
