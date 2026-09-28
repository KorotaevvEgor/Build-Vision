import { useEffect, useRef, useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { useAuth } from "../AuthContext";
import {
  ApiError,
  createProject,
  downloadScheduleTemplateUrl,
  fetchAssignableUsers,
  fetchProjectStatuses,
  type AssignableUser,
  type DraftCamera,
  type DraftFrameZone,
  type ProjectStatus,
} from "../api";
import { SiteBoundaryMap, type BoundaryMapMode } from "../components/SiteBoundaryMap";
import { CameraFleetMap } from "../components/CameraFleetMap";
import { FrameZoneDraftEditor } from "../components/FrameZoneDraftEditor";
import "./CreateProjectPage.css";

const MAX_PHOTOS = 10;
const TOTAL_STEPS_WITH_PHOTOS = 5;
const TOTAL_STEPS_WITHOUT_PHOTOS = 4;

let cameraDraftCounter = 0;
function nextCameraDraftId(): string {
  cameraDraftCounter += 1;
  return `cam-draft-${cameraDraftCounter}`;
}

interface PhotoDraft {
  file: File;
  previewUrl: string;
}

interface ScheduleErrorDetail {
  message: string;
  errors: string[];
}

function isScheduleErrorDetail(value: unknown): value is ScheduleErrorDetail {
  return (
    typeof value === "object" &&
    value !== null &&
    "errors" in value &&
    Array.isArray((value as { errors: unknown }).errors)
  );
}

export function CreateProjectPage() {
  const { user } = useAuth();
  const navigate = useNavigate();

  const [statuses, setStatuses] = useState<{ key: ProjectStatus; label_ru: string }[]>([]);
  const [users, setUsers] = useState<AssignableUser[]>([]);
  const [step, setStep] = useState(1);

  // Шаг 1 — данные проекта, видеопоток, карта.
  const [name, setName] = useState("");
  const [address, setAddress] = useState("");
  const [status, setStatus] = useState<ProjectStatus>("preparation");
  const [latitude, setLatitude] = useState("");
  const [longitude, setLongitude] = useState("");
  const [memberIds, setMemberIds] = useState<Set<number>>(new Set());
  const [boundary, setBoundary] = useState<[number, number][]>([]);
  const [mapMode, setMapMode] = useState<BoundaryMapMode>("point");

  // Шаг 2 — камеры и трансляции (создаются независимо от фото — только точка + ссылка).
  const [cameraDrafts, setCameraDrafts] = useState<DraftCamera[]>([]);
  const [activeCameraId, setActiveCameraId] = useState<string | null>(null);

  // Шаг 3 — календарный план.
  const [scheduleFile, setScheduleFile] = useState<File | null>(null);
  const [scheduleErrors, setScheduleErrors] = useState<string[]>([]);

  // Шаг 4 — фотографии.
  const [photos, setPhotos] = useState<PhotoDraft[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const photoInputRef = useRef<HTMLInputElement | null>(null);
  const photosRef = useRef<PhotoDraft[]>([]);
  useEffect(() => {
    photosRef.current = photos;
  }, [photos]);

  // Шаг 5 — камера и зоны на опорном фото.
  const [referencePhotoIndex, setReferencePhotoIndex] = useState(0);
  const [cameraName, setCameraName] = useState("Камера 1");
  const [cameraLatitude, setCameraLatitude] = useState("");
  const [cameraLongitude, setCameraLongitude] = useState("");
  const [frameZones, setFrameZones] = useState<DraftFrameZone[]>([]);
  const [referenceImageSize, setReferenceImageSize] = useState<{ width: number; height: number } | null>(
    null,
  );

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (user?.role !== "admin") return;
    fetchProjectStatuses()
      .then((data) => setStatuses(data.statuses))
      .catch(() => setStatuses([]));
    fetchAssignableUsers()
      .then((data) => setUsers(data.users))
      .catch(() => setUsers([]));
  }, [user]);

  // Освобождаем все object URL превью фото при размонтировании страницы.
  useEffect(() => {
    return () => {
      photosRef.current.forEach((photo) => URL.revokeObjectURL(photo.previewUrl));
    };
  }, []);

  if (user && user.role !== "admin") {
    // Скрытая кнопка в UI недостаточна — сервер тоже проверяет права (403),
    // но не даём даже открыть форму участнику без прав.
    return <Navigate to="/projects" replace />;
  }

  const totalSteps = photos.length > 0 ? TOTAL_STEPS_WITH_PHOTOS : TOTAL_STEPS_WITHOUT_PHOTOS;

  const toggleMember = (id: number) => {
    setMemberIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const addPhotos = (files: FileList | File[]) => {
    const incoming = Array.from(files).filter((file) => file.type.startsWith("image/"));
    if (incoming.length === 0) return;
    setPhotos((current) => {
      const merged = [
        ...current,
        ...incoming.map((file) => ({ file, previewUrl: URL.createObjectURL(file) })),
      ];
      if (merged.length > MAX_PHOTOS) {
        merged.slice(MAX_PHOTOS).forEach((photo) => URL.revokeObjectURL(photo.previewUrl));
      }
      return merged.slice(0, MAX_PHOTOS);
    });
  };

  const removePhoto = (index: number) => {
    setPhotos((current) => {
      const target = current[index];
      if (target) URL.revokeObjectURL(target.previewUrl);
      return current.filter((_, i) => i !== index);
    });
    setReferencePhotoIndex(0);
    setFrameZones([]);
    setReferenceImageSize(null);
  };

  const boundaryReady = boundary.length >= 3;

  const addCameraDraft = () => {
    setCameraDrafts((current) => {
      const id = nextCameraDraftId();
      setActiveCameraId(id);
      return [...current, { id, name: `Камера ${current.length + 1}`, streamUrl: "", latitude: null, longitude: null }];
    });
  };

  const updateCameraDraft = (id: string, patch: Partial<DraftCamera>) => {
    setCameraDrafts((current) => current.map((cam) => (cam.id === id ? { ...cam, ...patch } : cam)));
  };

  const removeCameraDraft = (id: string) => {
    setCameraDrafts((current) => current.filter((cam) => cam.id !== id));
    setActiveCameraId((current) => (current === id ? null : current));
  };

  const goToStep2 = () => {
    setError(null);
    if (!name.trim()) {
      setError("Укажите название проекта");
      return;
    }
    const hasLatitude = latitude.trim() !== "";
    const hasLongitude = longitude.trim() !== "";
    if (hasLatitude !== hasLongitude) {
      setError("Широта и долгота должны быть указаны вместе или обе пусты");
      return;
    }
    setStep(2);
  };

  const goToStep3 = () => {
    setError(null);
    if (cameraDrafts.length > 0 && !boundaryReady) {
      setError("Камеры привязываются к зоне по границе площадки — сначала нарисуйте её на карте (шаг 1)");
      return;
    }
    for (const cam of cameraDrafts) {
      if (!cam.name.trim()) {
        setError("Укажите название для каждой добавленной камеры");
        return;
      }
      if (cam.latitude === null || cam.longitude === null) {
        setError(`Укажите точку на карте для камеры «${cam.name}»`);
        return;
      }
    }
    setStep(3);
  };

  const goToStep4 = () => {
    setError(null);
    if (scheduleFile && !boundaryReady) {
      setError("Календарный план создаёт зоны по границе площадки — сначала нарисуйте её на карте (шаг 1)");
      return;
    }
    setStep(4);
  };

  const goToStep5OrSubmit = () => {
    setError(null);
    if (photos.length > 0 && !boundaryReady) {
      setError("Фотографии привязываются к зоне по границе площадки — сначала нарисуйте её на карте (шаг 1)");
      return;
    }
    if (photos.length > 0) {
      setStep(5);
    } else {
      void submit();
    }
  };

  const submit = async () => {
    if (submitting) return;
    setError(null);
    setScheduleErrors([]);

    const trimmedName = name.trim();
    if (!trimmedName) {
      setError("Укажите название проекта");
      setStep(1);
      return;
    }
    const parsedLatitude = latitude.trim() ? Number(latitude) : null;
    const parsedLongitude = longitude.trim() ? Number(longitude) : null;
    if ((parsedLatitude !== null && Number.isNaN(parsedLatitude)) || (parsedLongitude !== null && Number.isNaN(parsedLongitude))) {
      setError("Координаты должны быть числами");
      setStep(1);
      return;
    }

    setSubmitting(true);
    try {
      const { project } = await createProject({
        name: trimmedName,
        address: address.trim(),
        status,
        latitude: parsedLatitude,
        longitude: parsedLongitude,
        memberUserIds: Array.from(memberIds),
        boundary: boundaryReady ? boundary : undefined,
        scheduleExcelFile: scheduleFile,
        photos: photos.map((p) => p.file),
        cameraName: photos.length > 0 ? cameraName.trim() || "Камера 1" : undefined,
        cameraLatitude: cameraLatitude.trim() ? Number(cameraLatitude) : null,
        cameraLongitude: cameraLongitude.trim() ? Number(cameraLongitude) : null,
        frameZones: frameZones.length > 0 ? frameZones : undefined,
        referenceWidth: referenceImageSize?.width,
        referenceHeight: referenceImageSize?.height,
        cameras: cameraDrafts.length > 0 ? cameraDrafts : undefined,
      });
      navigate(`/projects/${project.project_id}`);
    } catch (err) {
      // Форма сохраняет введённые значения при ошибке — просто показываем
      // сообщение (или список ошибок календарного плана), не сбрасывая состояние.
      if (err instanceof ApiError && isScheduleErrorDetail(err.detail)) {
        setError(err.detail.message);
        setScheduleErrors(err.detail.errors);
        setStep(3);
      } else {
        setError(err instanceof Error ? err.message : "Не удалось создать проект");
      }
      setSubmitting(false);
    }
  };

  return (
    <div className="sk-create-project-page">
      <h1>Новый проект</h1>
      <p className="sk-create-project-page__steps">
        Шаг {Math.min(step, totalSteps)} из {totalSteps}
      </p>

      <div className="sk-panel sk-create-project-page__form">
        {step === 1 && (
          <div className="sk-create-project-page__step">
            <div className="sk-field">
              <label htmlFor="name">Название</label>
              <input
                id="name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
                maxLength={200}
                disabled={submitting}
              />
            </div>

            <div className="sk-field">
              <label htmlFor="address">Адрес</label>
              <input
                id="address"
                value={address}
                onChange={(e) => setAddress(e.target.value)}
                maxLength={300}
                disabled={submitting}
              />
            </div>

            <div className="sk-field">
              <label htmlFor="status">Статус проекта</label>
              <select
                id="status"
                value={status}
                onChange={(e) => setStatus(e.target.value as ProjectStatus)}
                disabled={submitting}
              >
                {statuses.map((s) => (
                  <option key={s.key} value={s.key}>
                    {s.label_ru}
                  </option>
                ))}
              </select>
            </div>

            <div className="sk-create-project-page__coords">
              <div className="sk-field">
                <label htmlFor="latitude">Широта (необязательно)</label>
                <input
                  id="latitude"
                  type="text"
                  inputMode="decimal"
                  value={latitude}
                  onChange={(e) => setLatitude(e.target.value)}
                  placeholder="55.7474"
                  disabled={submitting}
                />
              </div>
              <div className="sk-field">
                <label htmlFor="longitude">Долгота (необязательно)</label>
                <input
                  id="longitude"
                  type="text"
                  inputMode="decimal"
                  value={longitude}
                  onChange={(e) => setLongitude(e.target.value)}
                  placeholder="37.6036"
                  disabled={submitting}
                />
              </div>
            </div>

            <div className="sk-field">
              <label>Карта: точка проекта и граница площадки</label>
              <div className="sk-create-project-page__map-toolbar">
                <button
                  type="button"
                  className={`sk-button sk-button--secondary${mapMode === "point" ? " sk-button--active" : ""}`}
                  onClick={() => setMapMode("point")}
                  disabled={submitting}
                >
                  Ставить точку
                </button>
                <button
                  type="button"
                  className={`sk-button sk-button--secondary${mapMode === "boundary" ? " sk-button--active" : ""}`}
                  onClick={() => setMapMode("boundary")}
                  disabled={submitting}
                >
                  Рисовать границу
                </button>
                <button
                  type="button"
                  className="sk-button sk-button--secondary"
                  disabled={boundary.length === 0 || submitting}
                  onClick={() => setBoundary((current) => current.slice(0, -1))}
                >
                  Убрать точку границы
                </button>
                <button
                  type="button"
                  className="sk-button sk-button--secondary"
                  disabled={boundary.length === 0 || submitting}
                  onClick={() => setBoundary([])}
                >
                  Очистить границу
                </button>
                <span className="sk-table__muted">
                  {mapMode === "boundary"
                    ? `Точек границы: ${boundary.length} (нужно минимум 3)`
                    : "Клик по карте ставит точку проекта"}
                </span>
              </div>
              <SiteBoundaryMap
                latitude={latitude.trim() ? Number(latitude) : null}
                longitude={longitude.trim() ? Number(longitude) : null}
                boundary={boundary}
                mode={mapMode}
                onPointChange={(lat, lon) => {
                  setLatitude(lat.toFixed(6));
                  setLongitude(lon.toFixed(6));
                }}
                onBoundaryChange={setBoundary}
              />
            </div>

            <div className="sk-field">
              <label>Участники проекта</label>
              {users.length === 0 ? (
                <p className="sk-empty-state">Нет пользователей, доступных для назначения.</p>
              ) : (
                <div className="sk-create-project-page__members">
                  {users.map((u) => (
                    <label key={u.id} className="sk-checkbox">
                      <input
                        type="checkbox"
                        checked={memberIds.has(u.id)}
                        onChange={() => toggleMember(u.id)}
                        disabled={submitting}
                      />
                      {u.full_name} ({u.username})
                    </label>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {step === 2 && (
          <div className="sk-create-project-page__step">
            <p className="sk-table__muted">
              Добавьте камеры с видеотрансляцией — это просто ссылки для просмотра, само видео не
              анализируется. Сколько камер добавите — столько точек потом нужно будет отметить на карте. Шаг
              необязателен.
            </p>

            {cameraDrafts.length > 0 && !boundaryReady && (
              <p className="sk-empty-state">
                Сначала отметьте границу площадки на карте (шаг 1) — камеры должны быть привязаны
                к зоне.
              </p>
            )}

            {cameraDrafts.length > 0 && (
              <div className="sk-create-project-page__camera-list">
                {cameraDrafts.map((cam) => (
                  <div
                    key={cam.id}
                    className={`sk-create-project-page__camera-row${cam.id === activeCameraId ? " sk-create-project-page__camera-row--active" : ""}`}
                  >
                    <div className="sk-create-project-page__coords">
                      <div className="sk-field">
                        <label htmlFor={`camera-draft-name-${cam.id}`}>Название камеры</label>
                        <input
                          id={`camera-draft-name-${cam.id}`}
                          value={cam.name}
                          onChange={(e) => updateCameraDraft(cam.id, { name: e.target.value })}
                          disabled={submitting}
                        />
                      </div>
                      <div className="sk-field">
                        <label htmlFor={`camera-draft-stream-${cam.id}`}>Ссылка на трансляцию (необязательно)</label>
                        <input
                          id={`camera-draft-stream-${cam.id}`}
                          type="url"
                          value={cam.streamUrl}
                          onChange={(e) => updateCameraDraft(cam.id, { streamUrl: e.target.value })}
                          placeholder="https://..."
                          disabled={submitting}
                        />
                      </div>
                    </div>
                    <div className="sk-create-project-page__camera-row-actions">
                      <button
                        type="button"
                        className={`sk-button sk-button--secondary${cam.id === activeCameraId ? " sk-button--active" : ""}`}
                        onClick={() => setActiveCameraId(cam.id)}
                        disabled={submitting}
                      >
                        {cam.latitude !== null ? "Переставить на карте" : "Указать на карте"}
                      </button>
                      <span className="sk-table__muted">
                        {cam.latitude !== null && cam.longitude !== null
                          ? `${cam.latitude.toFixed(6)}, ${cam.longitude.toFixed(6)}`
                          : "Точка не указана"}
                      </span>
                      <button
                        type="button"
                        className="sk-button sk-button--secondary"
                        onClick={() => removeCameraDraft(cam.id)}
                        disabled={submitting}
                      >
                        Удалить
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}

            <button
              type="button"
              className="sk-button sk-button--secondary"
              onClick={addCameraDraft}
              disabled={submitting}
            >
              + Добавить камеру
            </button>

            {cameraDrafts.length > 0 && (
              <div className="sk-field">
                <label>
                  {activeCameraId
                    ? `Клик по карте поставит точку для «${cameraDrafts.find((c) => c.id === activeCameraId)?.name ?? ""}»`
                    : "Выберите камеру кнопкой «Указать на карте», затем кликните по карте"}
                </label>
                <CameraFleetMap
                  latitude={latitude.trim() ? Number(latitude) : null}
                  longitude={longitude.trim() ? Number(longitude) : null}
                  boundary={boundary}
                  cameras={cameraDrafts}
                  activeCameraId={activeCameraId}
                  onCameraPositionChange={(id, lat, lon) =>
                    updateCameraDraft(id, { latitude: lat, longitude: lon })
                  }
                />
              </div>
            )}
          </div>
        )}

        {step === 3 && (
          <div className="sk-create-project-page__step">
            <p className="sk-table__muted">
              Загрузите заполненный календарный план — работы, сроки и связи между ними. Все зоны из
              плана получат единую геометрию — границу площадки, нарисованную на шаге 1. Шаг
              необязателен.
            </p>
            <a
              className="sk-button sk-button--secondary"
              href={downloadScheduleTemplateUrl()}
              download
            >
              Скачать шаблон .xlsx
            </a>
            <div className="sk-field">
              <label htmlFor="schedule-file">Заполненный календарный план</label>
              <input
                id="schedule-file"
                type="file"
                accept=".xlsx"
                disabled={submitting}
                onChange={(e) => setScheduleFile(e.target.files?.[0] ?? null)}
              />
              {scheduleFile && (
                <p className="sk-table__muted">
                  Выбран файл: {scheduleFile.name}{" "}
                  <button
                    type="button"
                    className="sk-button sk-button--secondary"
                    onClick={() => setScheduleFile(null)}
                  >
                    Убрать
                  </button>
                </p>
              )}
            </div>
            {scheduleErrors.length > 0 && (
              <div className="sk-panel sk-panel--error">
                <strong>Ошибки в календарном плане:</strong>
                <ul>
                  {scheduleErrors.map((message, index) => (
                    <li key={index}>{message}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        {step === 4 && (
          <div className="sk-create-project-page__step">
            <p className="sk-table__muted">
              Фотографии со стройки будут сразу проанализированы и добавлены в историю проекта. До{" "}
              {MAX_PHOTOS} файлов за один раз — остальные можно добавить позже через камеру.
            </p>
            {!boundaryReady && (
              <p className="sk-empty-state">
                Сначала отметьте границу площадки на карте (шаг 1) — фотографии должны быть привязаны
                к зоне.
              </p>
            )}
            <div
              className={`sk-create-project-page__dropzone${dragOver ? " sk-create-project-page__dropzone--over" : ""}`}
              onDragOver={(event) => {
                event.preventDefault();
                setDragOver(true);
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={(event) => {
                event.preventDefault();
                setDragOver(false);
                if (event.dataTransfer.files?.length) addPhotos(event.dataTransfer.files);
              }}
              onClick={() => photoInputRef.current?.click()}
              role="button"
              tabIndex={0}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") photoInputRef.current?.click();
              }}
            >
              <input
                ref={photoInputRef}
                type="file"
                accept="image/*"
                multiple
                hidden
                onChange={(event) => {
                  if (event.target.files) addPhotos(event.target.files);
                  event.target.value = "";
                }}
              />
              <strong>Перетащите фотографии сюда</strong>
              <span>или нажмите, чтобы выбрать файлы — до {MAX_PHOTOS} штук</span>
            </div>

            {photos.length > 0 && (
              <div className="sk-create-project-page__photo-grid">
                {photos.map((photo, index) => (
                  <div key={photo.previewUrl} className="sk-create-project-page__photo">
                    <img src={photo.previewUrl} alt={photo.file.name} />
                    <button
                      type="button"
                      className="sk-button sk-button--secondary"
                      onClick={() => removePhoto(index)}
                    >
                      Удалить
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {step === 5 && photos.length > 0 && (
          <div className="sk-create-project-page__step">
            <p className="sk-table__muted">
              Задайте камеру, снявшую эти фотографии, и, если хотите, сразу обведите на одном из
              кадров зоны работы и простоя — это упростит дальнейший анализ. Шаг необязателен.
            </p>

            <div className="sk-create-project-page__coords">
              <div className="sk-field">
                <label htmlFor="camera-name">Название камеры</label>
                <input
                  id="camera-name"
                  value={cameraName}
                  onChange={(e) => setCameraName(e.target.value)}
                  disabled={submitting}
                />
              </div>
              <div className="sk-field">
                <label htmlFor="camera-latitude">Широта камеры</label>
                <input
                  id="camera-latitude"
                  type="text"
                  inputMode="decimal"
                  value={cameraLatitude}
                  onChange={(e) => setCameraLatitude(e.target.value)}
                  placeholder={latitude || "55.7474"}
                  disabled={submitting}
                />
              </div>
              <div className="sk-field">
                <label htmlFor="camera-longitude">Долгота камеры</label>
                <input
                  id="camera-longitude"
                  type="text"
                  inputMode="decimal"
                  value={cameraLongitude}
                  onChange={(e) => setCameraLongitude(e.target.value)}
                  placeholder={longitude || "37.6036"}
                  disabled={submitting}
                />
              </div>
            </div>

            {photos.length > 1 && (
              <div className="sk-field">
                <label htmlFor="reference-photo">Опорное фото для разметки зон</label>
                <select
                  id="reference-photo"
                  value={referencePhotoIndex}
                  onChange={(e) => {
                    setReferencePhotoIndex(Number(e.target.value));
                    setFrameZones([]);
                    setReferenceImageSize(null);
                  }}
                >
                  {photos.map((photo, index) => (
                    <option key={photo.previewUrl} value={index}>
                      {photo.file.name}
                    </option>
                  ))}
                </select>
              </div>
            )}

            {photos[referencePhotoIndex] && (
              <FrameZoneDraftEditor
                imageUrl={photos[referencePhotoIndex].previewUrl}
                zones={frameZones}
                onZonesChange={setFrameZones}
                onImageSize={setReferenceImageSize}
              />
            )}
          </div>
        )}

        {error && <p className="sk-create-project-page__error">{error}</p>}

        <div className="sk-create-project-page__actions">
          {step > 1 && (
            <button
              type="button"
              className="sk-button sk-button--secondary"
              onClick={() => setStep((s) => s - 1)}
              disabled={submitting}
            >
              Назад
            </button>
          )}
          {step === 1 && (
            <button type="button" className="sk-button" onClick={goToStep2} disabled={submitting}>
              Далее
            </button>
          )}
          {step === 2 && (
            <button type="button" className="sk-button" onClick={goToStep3} disabled={submitting}>
              Далее
            </button>
          )}
          {step === 3 && (
            <button type="button" className="sk-button" onClick={goToStep4} disabled={submitting}>
              Далее
            </button>
          )}
          {step === 4 && (
            <button type="button" className="sk-button" onClick={goToStep5OrSubmit} disabled={submitting}>
              {photos.length > 0 ? "Далее" : submitting ? "Создаём…" : "Создать проект"}
            </button>
          )}
          {step === 5 && (
            <button type="button" className="sk-button" onClick={() => void submit()} disabled={submitting}>
              {submitting ? "Создаём…" : "Создать проект"}
            </button>
          )}
          <button
            type="button"
            className="sk-button sk-button--secondary"
            onClick={() => navigate("/projects")}
            disabled={submitting}
          >
            Отмена
          </button>
        </div>
      </div>
    </div>
  );
}
