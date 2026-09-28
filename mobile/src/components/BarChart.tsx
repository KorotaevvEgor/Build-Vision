import "./BarChart.css";

interface Props {
  data: Record<string, unknown>[];
  labelKey: string;
  valueKey: string;
  colorFor?: (label: string) => string;
}

/** Простой столбчатый график без сторонних библиотек — общий компонент для Аналитики и др. страниц. */
export function BarChart({ data, labelKey, valueKey, colorFor }: Props) {
  const max = Math.max(1, ...data.map((d) => Number(d[valueKey])));
  return (
    <div className="sk-bar-chart">
      {data.map((d, index) => {
        const label = String(d[labelKey]);
        const value = Number(d[valueKey]);
        return (
          <div key={index} className="sk-bar-chart__col">
            <div className="sk-bar-chart__track">
              <div
                className="sk-bar-chart__bar"
                style={{ height: `${(value / max) * 100}%`, background: colorFor ? colorFor(label) : undefined }}
                title={`${label}: ${value}`}
              />
            </div>
            <div className="sk-bar-chart__label">{label}</div>
            <div className="sk-bar-chart__value">{value}</div>
          </div>
        );
      })}
    </div>
  );
}
