import { useEffect, useRef, useState } from "react";
import {
  analyzeDemoImage,
  demoSampleImageUrl,
  fetchDemoSamples,
  type DemoAnalysis,
  type DemoSample,
} from "../api";
import "./DemoPage.css";

const CLASS_COLOR_VARS: Record<string, string> = {
  excavator: "var(--sk-class-excavator)",
  dump_truck: "var(--sk-class-dump-truck)",
  mobile_crane: "var(--sk-class-mobile-crane)",
  crane_manipulator: "var(--sk-class-crane-manipulator)",
  concrete_mixer: "var(--sk-class-concrete-mixer)",
  bulldozer: "var(--sk-class-bulldozer)",
  road_roller: "var(--sk-class-road-roller)",
  truck: "var(--sk-class-truck)",
};

const CONFIDENCE_LABELS: Record<string, string> = {
  high: "высокая",
  medium: "средняя",
  low: "низкая",
};

function classColor(classKey: string): string {
  return CLASS_COLOR_VARS[classKey] ?? "var(--sk-class-unknown)";
}

/**
 * Тот же сценарий разбора снимка, что и на публичной `/demo` (см. DemoPage.tsx), но встроенный
 * в рабочее пространство: без шапки-визитки и ссылки «Войти» — пользователь уже авторизован.
 * Полезно как быстрый инструмент «что ИИ увидит на этом кадре» без привязки к конкретному
 * проекту/камере, например при обсуждении с заказчиком или проверке произвольной фотографии.
 */
export function PhotoAnalysisDemoPage() {
  const [samples, setSamples] = useState<DemoSample[]>([]);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [imageSize, setImageSize] = useState<{ width: number; height: number } | null>(null);
  const [result, setResult] = useState<DemoAnalysis | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);

  // URL превью создаётся через createObjectURL и обязан освобождаться,
  // иначе каждая новая фотография протекает в памяти вкладки.
  const objectUrlRef = useRef<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    fetchDemoSamples()
      .then((data) => setSamples(data.samples))
      .catch(() => setSamples([]));
    return () => {
      if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
    };
  }, []);

  const setPreview = (url: string, isObjectUrl: boolean) => {
    if (objectUrlRef.current) {
      URL.revokeObjectURL(objectUrlRef.current);
      objectUrlRef.current = null;
    }
    if (isObjectUrl) objectUrlRef.current = url;
    setPreviewUrl(url);
    setImageSize(null);
  };

  const analyze = async (file: File | Blob, filename: string) => {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      setResult(await analyzeDemoImage(file, filename));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось разобрать снимок");
    } finally {
      setLoading(false);
    }
  };

  const handleFile = (file: File) => {
    setPreview(URL.createObjectURL(file), true);
    void analyze(file, file.name);
  };

  const handleSample = async (sample: DemoSample) => {
    const url = demoSampleImageUrl(sample.id);
    setPreview(url, false);
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      // Пример лежит на сервере, но разбирается тем же путём, что и загруженный файл:
      // отдельной «быстрой дорожки» для готовых примеров нет, иначе демонстрация
      // показывала бы не то, что получит реальный пользователь.
      const response = await fetch(url);
      const blob = await response.blob();
      setResult(await analyzeDemoImage(blob, `${sample.id}.png`));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось разобрать пример");
    } finally {
      setLoading(false);
    }
  };

  const vision = result?.vision;

  return (
    <div className="sk-demo-page sk-demo-page--embedded">
      <header className="sk-demo-header">
        <div>
          <h1>Демонстрационный разбор фотографии</h1>
          <p>
            Загрузите снимок площадки — сервис найдёт технику, определит стадию работ, оценит
            готовность объекта и прочитает штамп даты на кадре. Файл используется только для
            разбора и не привязывается ни к одному проекту.
          </p>
        </div>
      </header>

      <div
        className={`sk-dropzone${dragOver ? " sk-dropzone--over" : ""}`}
        onDragOver={(event) => {
          event.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragOver(false);
          const file = event.dataTransfer.files?.[0];
          if (file) handleFile(file);
        }}
        onClick={() => fileInputRef.current?.click()}
        role="button"
        tabIndex={0}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") fileInputRef.current?.click();
        }}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*"
          hidden
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) handleFile(file);
          }}
        />
        <strong>Перетащите фотографию сюда</strong>
        <span>или нажмите, чтобы выбрать файл — JPG, PNG, до 12 МБ</span>
      </div>

      {samples.length > 0 && (
        <section className="sk-demo-samples">
          <h2>Или возьмите готовый пример</h2>
          <p className="sk-demo-samples__note">
            Кадры из демонстрационного набора. Подписи — не наши слова, а то, что система
            определила сама при подготовке выборки.
          </p>
          <div className="sk-demo-samples__grid">
            {samples.map((sample) => (
              <button
                key={sample.id}
                type="button"
                className="sk-demo-sample"
                onClick={() => void handleSample(sample)}
                disabled={loading}
              >
                <img src={demoSampleImageUrl(sample.id)} alt={sample.title} loading="lazy" />
                <span className="sk-demo-sample__title">{sample.title}</span>
                <span className="sk-demo-sample__meta">
                  {sample.readiness_percent !== null ? `готовность ${sample.readiness_percent}%` : "оценка не получена"}
                  {sample.date_stamp ? ` · ${sample.date_stamp}` : " · без штампа даты"}
                </span>
              </button>
            ))}
          </div>
        </section>
      )}

      {error && <div className="sk-panel sk-panel--error">{error}</div>}

      {(previewUrl || loading) && (
        <section className="sk-demo-result">
          <div className="sk-panel sk-demo-canvas">
            {loading && <div className="sk-demo-canvas__loading">Разбираем снимок…</div>}
            {previewUrl && (
              <div className="sk-demo-frame">
                <img
                  src={previewUrl}
                  alt="Разбираемый снимок"
                  onLoad={(event) =>
                    setImageSize({
                      width: event.currentTarget.naturalWidth,
                      height: event.currentTarget.naturalHeight,
                    })
                  }
                />
                {imageSize &&
                  result?.detections.map((detection, index) => {
                    const [x1, y1, x2, y2] = detection.bbox;
                    const color = detection.ambiguous
                      ? "var(--sk-status-warning)"
                      : !detection.in_taxonomy
                        ? "var(--sk-class-unknown)"
                        : classColor(detection.class_key);
                    return (
                      <div
                        key={index}
                        className="sk-demo-bbox"
                        style={{
                          left: `${(x1 / imageSize.width) * 100}%`,
                          top: `${(y1 / imageSize.height) * 100}%`,
                          width: `${((x2 - x1) / imageSize.width) * 100}%`,
                          height: `${((y2 - y1) / imageSize.height) * 100}%`,
                          borderColor: color,
                        }}
                      >
                        <span className="sk-demo-bbox__label" style={{ backgroundColor: color }}>
                          {detection.label_ru} {(detection.confidence * 100).toFixed(0)}%
                          {detection.ambiguous ? " · неоднозначно" : ""}
                        </span>
                      </div>
                    );
                  })}
              </div>
            )}
          </div>

          {result && (
            <div className="sk-demo-readout">
              {vision?.available ? (
                <div className="sk-panel">
                  <h2>Стадия работ</h2>
                  <p className="sk-demo-stage">{vision.stage_label}</p>
                  {vision.readiness_percent !== null && (
                    <div className="sk-readiness">
                      <div className="sk-readiness__head">
                        <span>Готовность объекта</span>
                        <strong>{vision.readiness_percent}%</strong>
                      </div>
                      <div className="sk-readiness__track">
                        <div
                          className="sk-readiness__fill"
                          style={{ width: `${vision.readiness_percent}%` }}
                        />
                      </div>
                    </div>
                  )}
                  <p className="sk-table__muted">
                    Уверенность: {CONFIDENCE_LABELS[vision.confidence] ?? vision.confidence}
                    {vision.date_stamp
                      ? ` · штамп даты на кадре: ${vision.date_stamp}`
                      : " · штамп даты не обнаружен"}
                  </p>
                  {vision.visual_evidence.length > 0 && (
                    <>
                      <p className="sk-table__muted">На чём основан вывод:</p>
                      <ul className="sk-demo-evidence">
                        {vision.visual_evidence.map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                    </>
                  )}
                </div>
              ) : (
                <div className="sk-panel">
                  <h2>Стадия работ</h2>
                  <p className="sk-table__muted">
                    Оценка стадии недоступна: языковая модель не ответила. Рамки с техникой ниже
                    получены детектором и остаются действительными.
                  </p>
                </div>
              )}

              <div className="sk-panel">
                <h2>Обнаруженная техника</h2>
                {result.equipment_counts.length === 0 ? (
                  <p className="sk-empty-state">
                    Техника из таксономии не распознана уверенно. Это может быть кадр без техники
                    или ограничение модели — система не выдаёт догадку за факт.
                  </p>
                ) : (
                  <table className="sk-table">
                    <thead>
                      <tr>
                        <th>Объект</th>
                        <th>Кол-во</th>
                        <th>Уверенность</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.equipment_counts.map((item) => (
                        <tr key={item.class_key}>
                          <td>
                            <span
                              className="sk-class-dot"
                              style={{ background: classColor(item.class_key) }}
                              aria-hidden="true"
                            />
                            {item.label_ru}
                          </td>
                          <td>{item.count}</td>
                          <td>{(item.max_confidence * 100).toFixed(0)}%</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}

                {result.known_limitations.length > 0 && (
                  <div className="sk-demo-limitation">
                    <strong>Честное предупреждение о качестве</strong>
                    {result.known_limitations.map((limitation) => (
                      <p key={limitation.class_key}>
                        <b>{limitation.label_ru}</b> (
                        {limitation.issue === "low_precision"
                          ? "низкая точность"
                          : "низкая полнота"}
                        ): {limitation.description}
                      </p>
                    ))}
                    <p className="sk-table__muted">
                      Цифры выше приведены как есть, без подгонки: мы сами измерили это
                      ограничение на размеченной выборке и показываем его рядом с результатом.
                    </p>
                  </div>
                )}
              </div>

              {result.comment.available && (
                <div className="sk-panel">
                  <h2>Комментарий</h2>
                  <p>{result.comment.text}</p>
                </div>
              )}

              <p className="sk-demo-note-block">{result.note}</p>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
