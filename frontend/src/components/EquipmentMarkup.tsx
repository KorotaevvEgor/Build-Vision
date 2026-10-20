import type { DemoAnalysis } from "../api";
import { classColor, type EquipmentMarkupState } from "./equipmentMarkupState";
import "./EquipmentMarkup.css";

interface AnnotatedPhotoProps {
  previewUrl: string;
  markup: EquipmentMarkupState;
  onImageSize: (size: { width: number; height: number }) => void;
}

/** Фото с цветными квадратами вокруг найденной техники. */
export function AnnotatedPhoto({ previewUrl, markup, onImageSize }: AnnotatedPhotoProps) {
  return (
    <div className="sk-demo-frame">
      <img
        src={previewUrl}
        alt="Разбираемый снимок"
        onLoad={(event) =>
          onImageSize({ width: event.currentTarget.naturalWidth, height: event.currentTarget.naturalHeight })
        }
      />
      {markup.boxes.map((box) => {
        const state =
          markup.highlight === null
            ? ""
            : markup.highlight === box.classKey
              ? " sk-markup-box--active"
              : " sk-markup-box--dim";
        return (
          <div
            key={box.id}
            className={`sk-markup-box${state}`}
            style={{
              left: `${box.left * 100}%`,
              top: `${box.top * 100}%`,
              width: `${box.width * 100}%`,
              height: `${box.height * 100}%`,
              borderColor: box.color,
              color: box.color,
            }}
            onMouseEnter={() => markup.setHighlight(box.classKey)}
            onMouseLeave={() => markup.setHighlight(null)}
          >
            <span
              className={`sk-markup-box__label${box.top < 0.07 ? " sk-markup-box__label--inside" : ""}`}
              style={{ backgroundColor: box.color }}
            >
              {box.label} {(box.confidence * 100).toFixed(0)}%{box.ambiguous ? " · неоднозначно" : ""}
            </span>
          </div>
        );
      })}
    </div>
  );
}

interface EquipmentPanelProps {
  markup: EquipmentMarkupState;
  result: DemoAnalysis;
}

/** Список определённой на фото техники — сбоку от снимка; наведение на строку подсвечивает рамки класса. */
export function EquipmentPanel({ markup, result }: EquipmentPanelProps) {
  const total = markup.counts.reduce((sum, item) => sum + item.count, 0);

  return (
    <div className="sk-panel sk-markup-panel">
      <div className="sk-markup-panel__head">
        <h2>Техника на фото</h2>
        {markup.hasAi && (
          <div className="sk-markup-toggle" role="group" aria-label="Источник разметки">
            <button
              type="button"
              className={markup.source === "ai" ? "sk-markup-toggle__btn--active" : ""}
              onClick={() => markup.setSource("ai")}
              title="Техника определена ИИ-моделью по нашему списку классов"
            >
              ИИ
            </button>
            <button
              type="button"
              className={markup.source === "detector" ? "sk-markup-toggle__btn--active" : ""}
              onClick={() => markup.setSource("detector")}
              title="Открытый детектор YOLO-World (для сравнения)"
            >
              Детектор
            </button>
          </div>
        )}
      </div>

      {markup.source === "ai" ? (
        <p className="sk-markup-panel__note">
          Определено ИИ-моделью строго по нашему списку классов техники. Рамки приблизительные.
        </p>
      ) : (
        <p className="sk-markup-panel__note">
          {markup.aiError
            ? `ИИ-разметка недоступна (${markup.aiError}) — показан результат детектора.`
            : "Результат открытого детектора YOLO-World."}
        </p>
      )}

      {markup.counts.length === 0 ? (
        <p className="sk-empty-state">
          Техника из нашего списка на снимке не найдена. Это может быть кадр без техники или ограничение
          модели — система не выдаёт догадку за факт.
        </p>
      ) : (
        <>
          <ul className="sk-markup-list">
            {markup.counts.map((item) => (
              <li key={item.class_key}>
                <button
                  type="button"
                  className={`sk-markup-list__row${markup.highlight === item.class_key ? " sk-markup-list__row--active" : ""}`}
                  onMouseEnter={() => markup.setHighlight(item.class_key)}
                  onMouseLeave={() => markup.setHighlight(null)}
                  onFocus={() => markup.setHighlight(item.class_key)}
                  onBlur={() => markup.setHighlight(null)}
                >
                  <span
                    className="sk-markup-dot"
                    style={{ background: classColor(item.class_key) }}
                    aria-hidden="true"
                  />
                  <span className="sk-markup-list__name">{item.label_ru}</span>
                  <span className="sk-markup-list__count">× {item.count}</span>
                  <span className="sk-markup-list__conf">{(item.max_confidence * 100).toFixed(0)}%</span>
                </button>
              </li>
            ))}
          </ul>
          <p className="sk-markup-panel__total">Всего единиц техники: {total}</p>
        </>
      )}

      {markup.source === "detector" && result.known_limitations.length > 0 && (
        <div className="sk-demo-limitation">
          <strong>Честное предупреждение о качестве</strong>
          {result.known_limitations.map((limitation) => (
            <p key={limitation.class_key}>
              <b>{limitation.label_ru}</b> (
              {limitation.issue === "low_precision" ? "низкая точность" : "низкая полнота"}):{" "}
              {limitation.description}
            </p>
          ))}
          <p className="sk-table__muted">
            Цифры выше приведены как есть, без подгонки: мы сами измерили это ограничение на размеченной выборке и
            показываем его рядом с результатом.
          </p>
        </div>
      )}
    </div>
  );
}
