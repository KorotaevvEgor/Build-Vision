import { useEffect, useRef, useState } from "react";
import {
  analyzeDemoImage,
  demoSampleImageUrl,
  fetchDemoSamples,
  type DemoAnalysis,
  type DemoSample,
} from "../api";
import { AnnotatedPhoto, EquipmentPanel } from "../components/EquipmentMarkup";
import { useEquipmentMarkup } from "../components/equipmentMarkupState";
import "./DemoPage.css";

const CONFIDENCE_LABELS: Record<string, string> = {
  high: "высокая",
  medium: "средняя",
  low: "низкая",
};

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
  const markup = useEquipmentMarkup(result, imageSize);

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
            {previewUrl && <AnnotatedPhoto previewUrl={previewUrl} markup={markup} onImageSize={setImageSize} />}
          </div>

          {result && (
            <div className="sk-demo-readout">
              <EquipmentPanel markup={markup} result={result} />

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
                    Оценка стадии недоступна: языковая модель не ответила. Рамки с техникой
                    получены детектором и остаются действительными.
                  </p>
                </div>
              )}

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
