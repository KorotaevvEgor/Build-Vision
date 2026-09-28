/**
 * Премиальные (не эмодзи) иконки для карточек статистики Главной страницы —
 * тот же дуотон-стиль от руки, что и в EquipmentIcons.tsx (viewBox 0 0 40 40,
 * цвет через currentColor), чтобы все четыре карточки выглядели единообразно.
 */
import type { SVGProps } from "react";

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

/** Камера наблюдения — для карточки «Камеры онлайн». */
export function CameraStatIcon(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M6 14h6l2.4-3.4h7.2L24 14h4a3 3 0 0 1 3 3v13a3 3 0 0 1-3 3H9a3 3 0 0 1-3-3V17a3 3 0 0 1 3-3z" fill="currentColor" opacity=".14" />
      <path d="M6 14h6l2.4-3.4h7.2L24 14h4a3 3 0 0 1 3 3v13a3 3 0 0 1-3 3H9a3 3 0 0 1-3-3V17a3 3 0 0 1 3-3z" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" />
      <circle cx="18.5" cy="23" r="5.4" stroke="currentColor" strokeWidth="1.7" fill="currentColor" fillOpacity=".16" />
      <circle cx="18.5" cy="23" r="2" fill="currentColor" />
      <circle cx="27" cy="18" r="1.4" fill="currentColor" />
    </Base>
  );
}

/** Треугольник с восклицательным знаком — для карточки «Отклонения». */
export function WarningStatIcon(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M20 6 36 32H4Z" fill="currentColor" opacity=".14" />
      <path d="M20 6 36 32H4Z" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" />
      <path d="M20 16v8" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
      <circle cx="20" cy="27.5" r="1.6" fill="currentColor" />
    </Base>
  );
}

/** Растущая столбчатая диаграмма — для карточки «Выполнение плана». */
export function ChartStatIcon(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M6 34V6" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
      <path d="M6 34h30" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
      <rect x="11" y="24" width="5" height="8" rx="1" fill="currentColor" opacity=".3" />
      <rect x="11" y="24" width="5" height="8" rx="1" stroke="currentColor" strokeWidth="1.4" />
      <rect x="19" y="17" width="5" height="15" rx="1" fill="currentColor" opacity=".3" />
      <rect x="19" y="17" width="5" height="15" rx="1" stroke="currentColor" strokeWidth="1.4" />
      <rect x="27" y="11" width="5" height="21" rx="1" fill="currentColor" opacity=".3" />
      <rect x="27" y="11" width="5" height="21" rx="1" stroke="currentColor" strokeWidth="1.4" />
      <path d="M11 15 18 10l6 3 8-7" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" opacity=".85" />
    </Base>
  );
}
