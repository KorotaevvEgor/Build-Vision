// Клиент backend API. Базовый URL настраивается через VITE_API_BASE_URL
// (см. .env.example); по умолчанию — тот же origin, что у сайта.
// В разработке /api перенаправляется в FastAPI через Vite proxy.

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

export type DeviationStatus = "no_deviation" | "possible_deviation" | "insufficient_data";

export interface StageSummary {
  stage_id: string;
  work_code: string;
  work_name: string;
  zone_id: string;
  start_date: string;
  end_date: string;
  technology_assumption: string;
}

export interface SiteResponse {
  geojson: GeoJSON.FeatureCollection;
  schedule_is_demo: boolean;
  stages: StageSummary[];
}

/** Работает / простаивает / судить нельзя — третье значение обязательное, см. backend/app/activity.py. */
export type DetectionActivity = "working" | "idle" | "unknown";

export interface Detection {
  class_key: string;
  label_ru: string;
  in_taxonomy: boolean;
  confidence: number;
  bbox: [number, number, number, number];
  ambiguous: boolean;
  runner_up_class_key: string | null;
  frame_zone_name?: string | null;
  frame_zone_kind?: FrameZoneKind | null;
  activity?: DetectionActivity;
  activity_reason?: string | null;
}

export interface QuantityCheck {
  class_key: string;
  label_ru: string;
  required_qty: number;
  actual_qty: number;
  satisfied: boolean;
}

export interface StageEvaluationResponse {
  stage_id: string;
  work_name: string;
  status: DeviationStatus;
  status_label_ru: string;
  /** Этап на критическом пути — отклонение по нему сдвигает дату сдачи. */
  is_critical?: boolean;
  required: string[];
  allowed: string[];
  quantity_checks: QuantityCheck[];
  missing_required: string[];
  explanation_ru: string;
  unexpected_detections: Detection[];
  ambiguous_detections: Detection[];
}

/** Оценка стадии и готовности по самой фотографии (независимо от детектора). */
export interface VisionAssessment {
  available: boolean;
  stage_key: string;
  stage_label: string;
  readiness_percent: number | null;
  visual_evidence: string[];
  equipment: string[];
  confidence: "high" | "medium" | "low";
  date_stamp: string | null;
  cached: boolean;
  model: string;
  error: string | null;
}

/** Расхождение между наблюдаемой на снимке стадией и этапом графика. */
export interface StageMismatch {
  observed_stage: string;
  scheduled_stages: string;
  message: string;
}

export interface LlmConclusion {
  available: boolean;
  text: string;
  model?: string;
  cached?: boolean;
  error?: string | null;
}

/** Отклонение, видное только через зоны кадра: простой, опасная зона, чужая зона, слепая зона. */
export interface ZoneDeviation {
  kind: string;
  severity: "critical" | "warning" | "info";
  title: string;
  message: string;
  equipment: string[];
}

/**
 * Блок ИИ-обогащения. Может быть выключен целиком (`enabled: false`) или
 * содержать недоступные части — интерфейс обязан показывать это честно,
 * а не подменять пустотой.
 */
export interface ObservationAi {
  enabled: boolean;
  reason: string | null;
  vision: VisionAssessment | null;
  conclusion: LlmConclusion | null;
  stage_mismatch: StageMismatch | null;
  /** Считаются геометрией и правилами, поэтому есть даже когда языковая модель отключена. */
  zone_deviations?: ZoneDeviation[];
}

export interface ObservationResponse {
  observation_id: string;
  saved_to_db: boolean;
  image_sha256: string;
  zone_id: string;
  observed_date: string | null;
  date_confirmed: boolean;
  overall_status: DeviationStatus;
  overall_status_label_ru: string;
  overall_explanation_ru: string;
  stages: StageEvaluationResponse[];
  detections: Detection[];
  ai?: ObservationAi;
}

export type FrameZoneKind = "work" | "parking" | "entrance" | "danger" | "uncontrolled";

export interface FrameZone {
  id?: number;
  name: string;
  kind: FrameZoneKind;
  kind_label_ru?: string;
  /** Точки в пикселях опорного кадра, а не в долях: так проще сверять с рамками детекций. */
  polygon: [number, number][];
  reference_width?: number;
  reference_height?: number;
  stage_id?: string | null;
  note?: string;
}

export interface FrameZonesResponse {
  camera_id: string;
  camera_name: string;
  zone_id: string;
  zones: FrameZone[];
  kinds: { key: FrameZoneKind; label_ru: string }[];
  stages: { stage_id: string; work_name: string }[];
}

export function fetchFrameZones(
  projectId: ProjectId,
  cameraId: string,
): Promise<FrameZonesResponse> {
  return requestJson(`/api/projects/${projectId}/cameras/${cameraId}/frame-zones`);
}

export function saveFrameZones(
  projectId: ProjectId,
  cameraId: string,
  payload: { reference_width: number; reference_height: number; zones: FrameZone[] },
): Promise<{ zones: FrameZone[] }> {
  return requestJson(`/api/projects/${projectId}/cameras/${cameraId}/frame-zones`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function cameraReferenceImageUrl(projectId: ProjectId, cameraId: string): string {
  return `${API_BASE_URL}/api/projects/${projectId}/cameras/${cameraId}/reference-image`;
}

export type VlmConfidenceLevel = "high" | "medium" | "low";

export interface AppSettings {
  detector_confidence: number;
  autolabel_min_vlm_confidence: VlmConfidenceLevel;
  ambiguity_margin: number;
  /** false — настройки не взяты из БД, показаны значения по умолчанию. */
  stored_in_database: boolean;
  detector_confidence_min: number;
  detector_confidence_max: number;
  vlm_confidence_choices: { key: VlmConfidenceLevel; label_ru: string }[];
}

export function fetchSettings(): Promise<AppSettings> {
  return requestJson("/api/settings");
}

export function updateSettings(payload: {
  detector_confidence?: number;
  autolabel_min_vlm_confidence?: VlmConfidenceLevel;
}): Promise<AppSettings> {
  return requestJson("/api/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

/** Точка фактической готовности: один обход, усреднённый по ракурсам. */
export interface ReadinessPoint {
  date: string;
  readiness_percent: number;
  /** Разброс между ракурсами одного обхода — честная мера неуверенности оценки. */
  spread: number;
  frames: number;
  stage_label: string;
}

export interface PlannedStageBand {
  stage_id: string;
  work_name: string;
  start_date: string;
  end_date: string;
  is_current: boolean;
}

export interface ReadinessResponse {
  available: boolean;
  today: string;
  fact: ReadinessPoint[];
  planned_stages: PlannedStageBand[];
  current_planned_work: string | null;
  last_observed_stage: string | null;
  mismatch: { kind: string; message: string } | null;
  method_note: string;
}

export function fetchReadiness(projectId: ProjectId): Promise<ReadinessResponse> {
  return requestJson<ReadinessResponse>(`/api/projects/${projectId}/readiness`);
}

// --- Участок надзора: все объекты инспектора на одном экране ---

export type ScheduleStatus = "behind" | "on_track" | "ahead" | "unknown";

export interface SupervisionObject {
  project_id: number;
  name: string;
  address: string;
  is_demo: boolean;
  observation_count: number;
  dated_observation_count: number;
  last_observation_date: string | null;
  days_since_last_observation: number | null;
  has_confirmed_dates: boolean;
  /** Слишком давно не было подтверждённых снимков — контроля нет. */
  is_stale: boolean;
  stage_label: string;
  readiness_percent: number | null;
  readiness_date: string | null;
  open_deviations: number;
  critical_deviations: number;
  on_critical_path_deviations: number;
  resolved_awaiting_confirmation: number;
  latest_observation_id: string | null;
  schedule_status: ScheduleStatus;
  schedule_status_label_ru: string;
  shift_days: number;
  planned_finish_date: string | null;
  projected_finish_date: string | null;
  current_work_name?: string | null;
  current_work_is_critical?: boolean;
}

export interface SupervisionResponse {
  available: boolean;
  generated_at: string;
  stale_after_days: number;
  totals: {
    objects: number;
    observations_total: number;
    observations_last_30_days: number;
    requires_decision: number;
    critical: number;
    awaiting_confirmation: number;
    objects_behind: number;
    objects_stale: number;
  };
  objects: SupervisionObject[];
  stale_objects: {
    project_id: number;
    name: string;
    days_since_last_observation: number | null;
    has_confirmed_dates: boolean;
  }[];
}

export function fetchSupervision(): Promise<SupervisionResponse> {
  return requestJson<SupervisionResponse>("/api/supervision");
}

export interface ReviewQueueItem {
  id: number;
  project_id: number;
  project_name: string;
  zone_name: string;
  kind: string;
  kind_label_ru: string;
  severity: "critical" | "warning" | "info";
  severity_label_ru: string;
  status: DeviationLifecycleStatus;
  status_label_ru: string;
  title: string;
  message: string;
  equipment: string[];
  work_name: string | null;
  is_on_critical_path: boolean;
  occurrence_count: number;
  assignee: string | null;
  observation_id: string | null;
  observed_date: string | null;
  detected_at: string;
}

export function fetchReviewQueue(limit = 40): Promise<{
  available: boolean;
  total: number;
  items: ReviewQueueItem[];
}> {
  return requestJson(`/api/supervision/queue?limit=${limit}`);
}

// --- Публичная демонстрация: единственный раздел API без авторизации ---

export interface DemoSample {
  id: string;
  title: string;
  scenario: string;
  season: string;
  stage_label: string;
  readiness_percent: number | null;
  date_stamp: string | null;
  /** Ответ модели уже в кэше — разбор появится практически мгновенно. */
  warmed: boolean;
}

export interface DemoAnalysis {
  detections: Detection[];
  equipment_counts: { class_key: string; label_ru: string; count: number; max_confidence: number }[];
  /** Измеренные ограничения по тем классам, которые реально нашлись на снимке. */
  known_limitations: KnownLimitation[];
  vision: VisionAssessment | null;
  comment: { available: boolean; text: string; model?: string; cached?: boolean; error?: string | null };
  image_sha256: string;
  note: string;
}

export function fetchDemoSamples(): Promise<{ available: boolean; samples: DemoSample[] }> {
  return requestJson("/api/demo/samples");
}

export function demoSampleImageUrl(sampleId: string): string {
  return `${API_BASE_URL}/api/demo/samples/${sampleId}/image`;
}

export async function analyzeDemoImage(file: File | Blob, filename: string): Promise<DemoAnalysis> {
  const formData = new FormData();
  formData.set("image", file, filename);
  return requestJson<DemoAnalysis>("/api/demo/analyze", { method: "POST", body: formData });
}

export type DeviationLifecycleStatus =
  | "detected"
  | "assigned"
  | "resolved"
  | "confirmed"
  | "dismissed";

export interface DeviationRecord {
  id: number;
  kind: string;
  kind_label_ru: string;
  severity: "critical" | "warning" | "info";
  severity_label_ru: string;
  status: DeviationLifecycleStatus;
  status_label_ru: string;
  title: string;
  message: string;
  equipment: string[];
  zone_id: string;
  zone_name: string;
  stage_id: string | null;
  work_name: string | null;
  is_on_critical_path: boolean;
  occurrence_count: number;
  auto_resolved: boolean;
  resolution_note: string;
  assignee: string | null;
  assignee_id: number | null;
  /** Снимок, на котором отклонение выявлено. */
  before_observation_id: string | null;
  /** Снимок, на котором его уже нет — находится автоматически. */
  after_observation_id: string | null;
  detected_at: string;
  resolved_at: string | null;
  confirmed_at: string | null;
}

export interface DeviationsResponse {
  available: boolean;
  items: DeviationRecord[];
  counts: Record<string, number>;
  statuses: { key: DeviationLifecycleStatus; label_ru: string }[];
}

export function fetchDeviations(
  projectId: ProjectId,
  status?: DeviationLifecycleStatus,
): Promise<DeviationsResponse> {
  const query = status ? `?status=${status}` : "";
  return requestJson<DeviationsResponse>(`/api/projects/${projectId}/deviations${query}`);
}

export function changeDeviationStatus(
  projectId: ProjectId,
  deviationId: number,
  payload: { status: DeviationLifecycleStatus; assignee_id?: number; note?: string },
): Promise<{ deviation: DeviationRecord }> {
  return requestJson(`/api/projects/${projectId}/deviations/${deviationId}/status`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export interface ProjectEventItem {
  id: number;
  kind: string;
  kind_label_ru: string;
  title: string;
  message: string;
  old_value: string;
  new_value: string;
  zone_name: string | null;
  observation_id: string | null;
  deviation_id: number | null;
  actor: string | null;
  created_at: string;
}

export function fetchProjectEvents(
  projectId: ProjectId,
  limit = 50,
): Promise<{ available: boolean; items: ProjectEventItem[] }> {
  return requestJson(`/api/projects/${projectId}/events?limit=${limit}`);
}

/** Состояние работы по факту фотоконтроля (см. backend/app/schedule_network.py). */
export type StageState =
  | "not_started"
  | "in_progress"
  | "done_on_time"
  | "overdue"
  | "unverified"
  | "started_early";

export interface NetworkStage {
  stage_id: string;
  work_code: string;
  work_name: string;
  zone_id: string;
  parent_id: string | null;
  predecessor_ids: string[];
  level: number;
  is_summary: boolean;
  planned_start_date: string;
  planned_end_date: string;
  duration_days: number;
  early_start_date: string;
  early_finish_date: string;
  late_start_date: string;
  late_finish_date: string;
  /** Запас времени в днях: ноль означает критический путь. */
  total_float_days: number;
  is_critical: boolean;
  projected_finish_date: string;
  state: StageState | "";
  state_label_ru: string;
  delay_days: number;
  observation_count: number;
  compliance_percent: number | null;
  reason: string;
  /** Отставание превышает запас — работа двигает дату сдачи объекта. */
  shifts_project_finish: boolean;
}

export interface DelayBreakdownCategory {
  key: "missing_equipment" | "weather" | "schedule_deviation" | string;
  label_ru: string;
  days: number;
  share_percent: number;
}

export interface DelayBreakdown {
  available: boolean;
  shift_days: number;
  categories: DelayBreakdownCategory[];
  method_note: string;
}

export interface ScheduleNetworkResponse {
  available: boolean;
  reason: string;
  /** Работы, замкнутые в цикл связей: пока он не разорван, расчёт невозможен. */
  cycle: string[];
  baseline_finish_date: string | null;
  projected_finish_date: string | null;
  shift_days: number;
  status: "behind" | "on_track" | "ahead";
  status_label_ru: string;
  stages: NetworkStage[];
  critical_stage_ids: string[];
  unverified_stage_ids: string[];
  schedule_is_demo: boolean;
  delay_breakdown: DelayBreakdown;
}

export function fetchScheduleNetwork(projectId: ProjectId): Promise<ScheduleNetworkResponse> {
  return requestJson<ScheduleNetworkResponse>(`/api/projects/${projectId}/schedule-network`);
}

export interface StageRuleResponse {
  work_name: string;
  required: string[];
  required_quantities: Record<string, number>;
  allowed: string[];
  alternatives_note: string;
}

export interface KnownLimitation {
  class_key: string;
  label_ru: string;
  issue: string;
  description: string;
}

export interface RulesResponse {
  ambiguity_margin: number;
  stage_rules: Record<string, StageRuleResponse>;
  confusable_class_pairs: [string, string][];
  known_limitations: KnownLimitation[];
}

export class ApiError extends Error {
  status: number;
  /** Разобранное поле `detail` из ответа FastAPI (строка или структура с детальными ошибками), если тело — JSON. */
  detail: unknown;

  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (!["GET", "HEAD", "OPTIONS"].includes((init?.method ?? "GET").toUpperCase())) {
    // Нестандартный заголовок нельзя отправить чужой HTML-формой.
    // Вместе с серверной проверкой Origin/CORS он защищает cookie API от CSRF.
    headers.set("X-BuildVision-Request", "1");
  }
  // credentials: "include" — авторизация идёт через cookie сессии Django
  // (см. backend/app/auth.py), без этого браузер не отправит sessionid на другой порт/домен.
  const response = await fetch(`${API_BASE_URL}${path}`, { credentials: "include", ...init, headers });
  if (!response.ok) {
    const body = await response.text().catch(() => "");
    let detail: unknown;
    try {
      detail = (JSON.parse(body) as { detail?: unknown }).detail;
    } catch {
      detail = undefined;
    }
    throw new ApiError(response.status, `${response.status} ${response.statusText}: ${body}`, detail);
  }
  return response.json() as Promise<T>;
}

export type UserRole = "admin" | "participant";

export interface CurrentUser {
  id: number;
  username: string;
  full_name: string;
  role: UserRole;
  role_label: string;
  position: string;
  display_position: string;
  /** Относительный путь к аватару или null, если он не загружен — собирать в URL через avatarUrl(). */
  avatar_url: string | null;
  /** ISO-дата регистрации в системе. */
  date_joined: string;
  /** ISO-дата последнего входа; null для первого входа за текущую сессию. */
  last_login: string | null;
}

/** Собирает абсолютный URL аватара из относительного пути, как и другие *ImageUrl-хелперы выше. */
export function avatarUrl(user: Pick<CurrentUser, "avatar_url">): string | null {
  return user.avatar_url ? `${API_BASE_URL}${user.avatar_url}` : null;
}

export async function login(username: string, password: string): Promise<CurrentUser> {
  const formData = new FormData();
  formData.set("username", username);
  formData.set("password", password);
  const { user } = await requestJson<{ user: CurrentUser }>("/api/auth/login", {
    method: "POST",
    body: formData,
  });
  return user;
}

export async function logout(): Promise<void> {
  await requestJson<{ status: string }>("/api/auth/logout", { method: "POST" });
}

export async function fetchMe(): Promise<CurrentUser> {
  const { user } = await requestJson<{ user: CurrentUser }>("/api/auth/me");
  return user;
}

export async function updateProfile(payload: { position?: string }): Promise<CurrentUser> {
  const { user } = await requestJson<{ user: CurrentUser }>("/api/auth/profile", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return user;
}

export async function changePassword(currentPassword: string, newPassword: string): Promise<void> {
  await requestJson("/api/auth/change-password", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  });
}

export async function uploadAvatar(file: File): Promise<CurrentUser> {
  const formData = new FormData();
  formData.set("avatar", file, file.name);
  const { user } = await requestJson<{ user: CurrentUser }>("/api/auth/avatar", {
    method: "POST",
    body: formData,
  });
  return user;
}

export async function deleteAvatar(): Promise<CurrentUser> {
  const { user } = await requestJson<{ user: CurrentUser }>("/api/auth/avatar", { method: "DELETE" });
  return user;
}

export async function logoutAllSessions(): Promise<{ sessions_ended: number }> {
  return requestJson("/api/auth/sessions/logout-all", { method: "POST" });
}

export type ProjectId = string | number;

export type ProjectStatus = "preparation" | "construction" | "paused" | "completed";

export interface ProjectSummary {
  project_id: number;
  name: string;
  address: string;
  status: ProjectStatus;
  status_label_ru: string;
  latitude: number | null;
  longitude: number | null;
  has_boundary: boolean;
  is_legacy: boolean;
  current_stage_work_name: string | null;
  /** Доля прошедших дней текущего этапа (честная эвристика, не факт выполнения) — null без активного этапа. */
  current_stage_progress_percent: number | null;
  /** Камера с хотя бы одним снимком — для фото-превью на карточке, через cameraReferenceImageUrl. */
  photo_camera_id: string | null;
  total_observations: number;
  open_deviations_count: number;
}

export interface ProjectDetail {
  project_id: number;
  name: string;
  address: string;
  status: ProjectStatus;
  status_label_ru: string;
  latitude: number | null;
  longitude: number | null;
  has_boundary: boolean;
  is_legacy: boolean;
  note: string;
}

export function fetchProjects(): Promise<{ projects: ProjectSummary[] }> {
  return requestJson("/api/projects");
}

export function fetchProjectDetail(projectId: ProjectId): Promise<ProjectDetail> {
  return requestJson(`/api/projects/${projectId}`);
}

/** Необратимо удаляет проект вместе со всей историей. `confirmName` должен точно совпадать с названием проекта. */
export async function deleteProject(projectId: ProjectId, confirmName: string): Promise<void> {
  await requestJson(`/api/projects/${projectId}`, {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ confirm_name: confirmName }),
  });
}

export function fetchProjectStatuses(): Promise<{ statuses: { key: ProjectStatus; label_ru: string }[] }> {
  return requestJson("/api/projects/statuses");
}

export interface AssistantMessage {
  role: "user" | "assistant";
  content: string;
}

export interface AssistantAskResponse {
  available: boolean;
  answer: string;
  error: string | null;
}

/** Вопрос ИИ-ассистенту проекта — отвечает только по данным этого проекта, см. backend/app/assistant.py. */
export function askProjectAssistant(
  projectId: ProjectId,
  question: string,
  history: AssistantMessage[],
): Promise<AssistantAskResponse> {
  return requestJson(`/api/projects/${projectId}/assistant/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, history }),
  });
}

export interface AssignableUser {
  id: number;
  username: string;
  full_name: string;
}

export function fetchAssignableUsers(): Promise<{ users: AssignableUser[] }> {
  return requestJson("/api/projects/assignable-users");
}

/** Одна зона кадра, нарисованная на локальном превью на шаге создания проекта (без stage_id — этапов ещё нет). */
export interface DraftFrameZone {
  name: string;
  kind: FrameZoneKind;
  polygon: [number, number][];
  note?: string;
}

/**
 * Одна камера из списка на шаге «Камеры и трансляции» визарда создания проекта.
 * Отдельно от одиночной камеры для фото (см. cameraName/cameraLatitude ниже) —
 * эти камеры создаются только ради ссылки на трансляцию и точки на карте.
 */
export interface DraftCamera {
  id: string;
  name: string;
  streamUrl: string;
  latitude: number | null;
  longitude: number | null;
}

export interface CreateProjectParams {
  name: string;
  address: string;
  status: ProjectStatus;
  latitude: number | null;
  longitude: number | null;
  memberUserIds: number[];
  /** Точки границы [lon, lat] по порядку обхода контура; минимум 3 точки. */
  boundary?: [number, number][];
  scheduleExcelFile?: File | null;
  photos?: File[];
  cameraName?: string;
  cameraExternalId?: string;
  cameraLatitude?: number | null;
  cameraLongitude?: number | null;
  cameraZoneName?: string | null;
  frameZones?: DraftFrameZone[];
  referenceWidth?: number;
  referenceHeight?: number;
  /** Дополнительные камеры с трансляцией, не связанные с загружаемыми фото (см. DraftCamera). */
  cameras?: DraftCamera[];
}

export interface ProjectPhotoResult {
  filename: string;
  status: "ok" | "error";
  observation_id?: string;
  detections_count?: number;
  error?: string;
}

export interface CreateProjectResponse {
  project: ProjectSummary;
  schedule_import: { zones_created: number; stages_created: number };
  photos: ProjectPhotoResult[];
  frame_zones_saved: boolean;
  cameras_created: number;
}

export function createProject(params: CreateProjectParams): Promise<CreateProjectResponse> {
  const formData = new FormData();
  formData.set("name", params.name);
  formData.set("address", params.address);
  formData.set("status", params.status);
  if (params.latitude !== null) formData.set("latitude", String(params.latitude));
  if (params.longitude !== null) formData.set("longitude", String(params.longitude));
  for (const id of params.memberUserIds) formData.append("member_user_ids", String(id));
  if (params.boundary && params.boundary.length >= 3) {
    formData.set("boundary_geojson", JSON.stringify(params.boundary));
  }
  if (params.scheduleExcelFile) {
    formData.set("schedule_excel", params.scheduleExcelFile, params.scheduleExcelFile.name);
  }
  for (const photo of params.photos ?? []) {
    formData.append("photos", photo, photo.name);
  }
  if (params.cameraName) formData.set("camera_name", params.cameraName);
  if (params.cameraExternalId) formData.set("camera_external_id", params.cameraExternalId);
  if (params.cameraLatitude !== null && params.cameraLatitude !== undefined) {
    formData.set("camera_latitude", String(params.cameraLatitude));
  }
  if (params.cameraLongitude !== null && params.cameraLongitude !== undefined) {
    formData.set("camera_longitude", String(params.cameraLongitude));
  }
  if (params.cameraZoneName) formData.set("camera_zone_name", params.cameraZoneName);
  if (params.frameZones && params.frameZones.length > 0) {
    formData.set("frame_zones", JSON.stringify(params.frameZones));
    if (params.referenceWidth) formData.set("reference_width", String(params.referenceWidth));
    if (params.referenceHeight) formData.set("reference_height", String(params.referenceHeight));
  }
  if (params.cameras && params.cameras.length > 0) {
    formData.set(
      "cameras",
      JSON.stringify(
        params.cameras.map((cam) => ({
          name: cam.name,
          stream_url: cam.streamUrl,
          latitude: cam.latitude,
          longitude: cam.longitude,
        })),
      ),
    );
  }
  return requestJson<CreateProjectResponse>("/api/projects", { method: "POST", body: formData });
}

/** Ссылка для скачивания шаблона календарного плана (см. `download_schedule_template` на бэкенде). */
export function downloadScheduleTemplateUrl(): string {
  return `${API_BASE_URL}/api/projects/schedule-template`;
}

export function fetchSite(projectId: ProjectId): Promise<SiteResponse> {
  return requestJson<SiteResponse>(`/api/projects/${projectId}/site`);
}

export function fetchRules(projectId: ProjectId): Promise<RulesResponse> {
  return requestJson<RulesResponse>(`/api/projects/${projectId}/rules`);
}

export interface ZoneStageOnDate {
  stage_id: string;
  work_name: string;
  start_date: string;
  end_date: string;
  rule: { required: string[]; allowed: string[] } | null;
}

/** Этапы зоны, актуальные на указанную дату -- для режима истории кадров камеры на Главной: без `on_date`
 * вернёт все этапы зоны. */
export function fetchZoneStagesOnDate(
  projectId: ProjectId,
  zoneId: string,
  onDate?: string,
): Promise<{ zone_id: string; stages: ZoneStageOnDate[] }> {
  return requestJson(`/api/projects/${projectId}/zones/${zoneId}/stages${onDate ? `?on_date=${onDate}` : ""}`);
}

export interface VocabularyClassSummary {
  key: string;
  label_ru: string;
}

export function fetchVocabulary(): Promise<{ classes: VocabularyClassSummary[] }> {
  return requestJson("/api/vocabulary");
}

export interface WeatherRiskPeriod {
  stage_id: string;
  work_name: string;
  factor: string;
  comparison: "gte" | "lte";
  threshold: number;
  units: string;
  start_time_utc: string;
  end_time_utc: string;
  peak_value: number;
  message: string;
}

export interface WeatherRiskResponse {
  status: "ok" | "unavailable";
  provider: string;
  latitude: number;
  longitude: number;
  fetched_at: string | null;
  is_stale: boolean;
  error: string | null;
  location_is_demo: boolean;
  risk_periods: WeatherRiskPeriod[];
}

export function fetchWeatherRisks(projectId: ProjectId): Promise<WeatherRiskResponse> {
  return requestJson<WeatherRiskResponse>(`/api/projects/${projectId}/weather-risks`);
}

/** Один день посуточного прогноза в развороте виджета погоды. */
export interface DailyForecastDay {
  date: string;
  weather_code: number | null;
  description_ru: string | null;
  temperature_max: number | null;
  temperature_min: number | null;
  precipitation_probability_max: number | null;
  wind_speed_max: number | null;
}

/** Фактическая погода на объекте прямо сейчас + прогноз — для виджета в шапке (см. HeaderWeather.tsx). */
export interface CurrentWeatherResponse {
  status: "ok" | "unavailable" | "no_location";
  address: string;
  temperature: number | null;
  weather_code: number | null;
  description_ru: string | null;
  wind_speed: number | null;
  is_day: boolean | null;
  fetched_at: string | null;
  is_stale: boolean;
  error: string | null;
  daily: DailyForecastDay[];
}

export function fetchCurrentWeather(projectId: ProjectId): Promise<CurrentWeatherResponse> {
  return requestJson<CurrentWeatherResponse>(`/api/projects/${projectId}/current-weather`);
}

export interface CreateObservationParams {
  projectId: ProjectId;
  zoneId: string;
  observedDate?: string;
  dateConfirmed: boolean;
  /** Без камеры сервер не сможет применить зоны кадра и сравнить с предыдущими снимками. */
  cameraId?: string;
  image: File;
}

export async function createObservation(
  params: CreateObservationParams,
): Promise<ObservationResponse> {
  const formData = new FormData();
  formData.set("zone_id", params.zoneId);
  formData.set("date_confirmed", String(params.dateConfirmed));
  if (params.observedDate) {
    formData.set("observed_date", params.observedDate);
  }
  if (params.cameraId) {
    formData.set("camera_id", params.cameraId);
  }
  formData.set("image", params.image);

  return requestJson<ObservationResponse>(`/api/projects/${params.projectId}/observations`, {
    method: "POST",
    body: formData,
  });
}

export interface ObservationSummary {
  observation_id: string;
  overall_status: DeviationStatus;
  overall_status_label_ru: string;
  created_at: string;
  observed_date: string | null;
  image_path: string;
}

export interface CurrentStageSummary {
  stage_id: string;
  work_name: string;
  zone_id: string;
  start_date: string;
  end_date: string;
  progress_percent: number;
}

export interface ZoneDashboardSummary {
  zone_id: string;
  name: string;
  latest_observation: ObservationSummary | null;
}

export interface CameraSummary {
  camera_id: string;
  name: string;
  zone_id: string;
  zone_name: string;
  latitude: number;
  longitude: number;
  stream_url: string;
  is_demo: boolean;
  latest_observation: ObservationSummary | null;
}

export interface NotificationItem {
  observation_id: string;
  severity: "critical" | "info";
  zone_id: string;
  zone_name: string;
  created_at: string;
  title: string;
  explanation_ru: string;
  status_label_ru: string;
  quantity_checks: QuantityCheck[];
}

export interface RiskFactor {
  key: string;
  severity: "high" | "medium" | "low";
  message: string;
}

export interface DashboardResponse {
  available: boolean;
  zone_count: number;
  camera_count: number;
  active_stage_count: number;
  current_stage: CurrentStageSummary | null;
  plan_completion_percent: number | null;
  recognized_equipment_type_count: number;
  deviation_count_24h: number;
  deviation_count_7d: number;
  zones: ZoneDashboardSummary[];
  cameras: CameraSummary[];
  top_risk_factor: RiskFactor | null;
  recent_deviations: NotificationItem[];
}

export function fetchDashboard(projectId: ProjectId): Promise<DashboardResponse> {
  return requestJson<DashboardResponse>(`/api/projects/${projectId}/dashboard`);
}

export function fetchCameras(projectId: ProjectId): Promise<{ cameras: CameraSummary[] }> {
  return requestJson<{ cameras: CameraSummary[] }>(`/api/projects/${projectId}/cameras`);
}

export interface CameraDetail extends CameraSummary {
  recent_observations: ObservationSummary[];
}

export function fetchCamera(projectId: ProjectId, cameraId: string): Promise<CameraDetail> {
  return requestJson<CameraDetail>(`/api/projects/${projectId}/cameras/${cameraId}`);
}

// --- Редактор карты: зоны и камеры (CRUD, только администратор) ---

export type ZoneKind = "work" | "parking" | "entrance" | "danger" | "uncontrolled";

export interface ZoneKindChoice {
  key: ZoneKind;
  label_ru: string;
}

export interface ZoneDetail {
  zone_id: string;
  name: string;
  kind: ZoneKind;
  kind_label_ru: string;
  description: string;
  geometry_geojson: GeoJSON.Polygon;
  stage_count: number;
  camera_count: number;
}

export function fetchZones(projectId: ProjectId): Promise<{ zones: ZoneDetail[]; kinds: ZoneKindChoice[] }> {
  return requestJson(`/api/projects/${projectId}/zones`);
}

export interface ZoneCreatePayload {
  name: string;
  kind: ZoneKind;
  /** [долгота, широта], как в GeoJSON — не путать с Leaflet LatLng ([широта, долгота]). */
  points: [number, number][];
  description?: string;
}

export function createZone(projectId: ProjectId, payload: ZoneCreatePayload): Promise<{ zone: ZoneDetail }> {
  return requestJson(`/api/projects/${projectId}/zones`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export interface ZoneUpdatePayload {
  name: string;
  kind: ZoneKind;
  /** Пропущено — контур остаётся как есть, меняется только название/тип/описание. */
  points?: [number, number][];
  description?: string;
}

export function updateZone(
  projectId: ProjectId,
  zoneId: string,
  payload: ZoneUpdatePayload,
): Promise<{ zone: ZoneDetail }> {
  return requestJson(`/api/projects/${projectId}/zones/${zoneId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function deleteZone(projectId: ProjectId, zoneId: string): Promise<void> {
  await requestJson(`/api/projects/${projectId}/zones/${zoneId}`, { method: "DELETE" });
}

export interface EditableCamera {
  camera_id: string;
  name: string;
  zone_id: string;
  zone_name: string;
  latitude: number;
  longitude: number;
  stream_url: string;
}

export interface CameraCreatePayload {
  name: string;
  zone_id: string;
  latitude: number;
  longitude: number;
  stream_url?: string;
  external_id?: string;
}

export function createCamera(
  projectId: ProjectId,
  payload: CameraCreatePayload,
): Promise<{ camera: EditableCamera }> {
  return requestJson(`/api/projects/${projectId}/cameras`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export interface CameraUpdatePayload {
  name: string;
  zone_id: string;
  latitude: number;
  longitude: number;
  stream_url?: string;
}

export function updateCamera(
  projectId: ProjectId,
  cameraId: string,
  payload: CameraUpdatePayload,
): Promise<{ camera: EditableCamera }> {
  return requestJson(`/api/projects/${projectId}/cameras/${cameraId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function deleteCamera(projectId: ProjectId, cameraId: string): Promise<void> {
  await requestJson(`/api/projects/${projectId}/cameras/${cameraId}`, { method: "DELETE" });
}

// --- Редактор календарного плана: этапы (CRUD, только администратор для записи) ---

export interface StageRequiredItemDetail {
  class_key: string;
  label_ru: string;
  min_quantity: number;
}

export interface StageDetail {
  stage_id: string;
  work_code: string;
  work_name: string;
  zone_id: string;
  zone_name: string;
  start_date: string;
  end_date: string;
  parent_id: string | null;
  predecessor_ids: string[];
  technology_assumption: string;
  required: StageRequiredItemDetail[];
  allowed: string[];
  alternatives_note: string;
}

export function fetchStages(projectId: ProjectId): Promise<{ stages: StageDetail[] }> {
  return requestJson(`/api/projects/${projectId}/stages`);
}

export interface StageRequiredItemPayload {
  class_key: string;
  min_quantity: number;
}

export interface StageWritePayload {
  work_name: string;
  work_code?: string;
  zone_id: string;
  start_date: string;
  end_date: string;
  parent_id?: string | null;
  predecessor_ids?: string[];
  technology_assumption?: string;
  required?: StageRequiredItemPayload[];
  allowed?: string[];
  alternatives_note?: string;
}

export function createStage(projectId: ProjectId, payload: StageWritePayload): Promise<{ stage: StageDetail }> {
  return requestJson(`/api/projects/${projectId}/stages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function updateStage(
  projectId: ProjectId,
  stageId: string,
  payload: StageWritePayload,
): Promise<{ stage: StageDetail }> {
  return requestJson(`/api/projects/${projectId}/stages/${stageId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function deleteStage(projectId: ProjectId, stageId: string): Promise<void> {
  await requestJson(`/api/projects/${projectId}/stages/${stageId}`, { method: "DELETE" });
}

export function fetchNotifications(
  projectId: ProjectId,
  limit = 20,
): Promise<{ available: boolean; items: NotificationItem[] }> {
  return requestJson(`/api/projects/${projectId}/notifications?limit=${limit}`);
}

export interface AnalyticsResponse {
  available: boolean;
  /** Ключ месяца в формате "YYYY-MM" — агрегация по месяцам, а не по дням: аналитика часто
   * охватывает весь проект, и поденный график был бы слишком длинным и разреженным. */
  deviations_by_month: { month: string; count: number }[];
  equipment_counts: { class_key: string; label_ru: string; count: number }[];
  total_observations: number;
}

export function fetchAnalytics(projectId: ProjectId, days = 14): Promise<AnalyticsResponse> {
  return requestJson<AnalyticsResponse>(`/api/projects/${projectId}/analytics?days=${days}`);
}

export interface ObservationDetail {
  observation_id: string;
  zone_id: string;
  image_sha256: string;
  observed_date: string | null;
  date_confirmed: boolean;
  overall_status: DeviationStatus;
  overall_status_label_ru: string;
  overall_explanation_ru: string;
  created_at: string;
  detections: Detection[];
  stages: StageEvaluationResponse[];
}

export function fetchObservation(projectId: ProjectId, observationId: string): Promise<ObservationDetail> {
  return requestJson<ObservationDetail>(`/api/projects/${projectId}/observations/${observationId}`);
}

export interface ForecastResponse {
  available: boolean;
  reason?: string;
  stage_id?: string;
  work_name?: string;
  zone_id?: string;
  planned_start_date?: string;
  planned_days?: number;
  planned_end_date?: string;
  projected_end_date?: string;
  delay_days?: number;
  average_compliance_percent?: number | null;
  current_compliance_percent?: number | null;
  observation_count?: number;
  risk_factors?: RiskFactor[];
}

export function fetchStageForecast(projectId: ProjectId, zoneId?: string): Promise<ForecastResponse> {
  return requestJson<ForecastResponse>(
    `/api/projects/${projectId}/forecast${zoneId ? `?zone_id=${zoneId}` : ""}`,
  );
}

/**
 * URL снимка наблюдения. Эндпоинт защищён сессией — если фронтенд и API на
 * разных origin (локальная разработка), нужно ставить `crossOrigin="use-credentials"`
 * на <img>, иначе браузер не отправит cookie сессии на чужой origin.
 */
export function getObservationImageUrl(projectId: ProjectId, observationId: string): string {
  return `${API_BASE_URL}/api/projects/${projectId}/observations/${observationId}/image`;
}

// --- Модуль «AI Learning»: коррекции инженера и версии классификатора-корректора ---

export interface CreateCorrectionParams {
  projectId: ProjectId;
  observationId: string;
  bbox: [number, number, number, number];
  originalClassKey: string;
  originalConfidence: number | null;
  correctedClassKey: string | null;
}

export interface CorrectionSummary {
  id: number;
  crop_image_path: string;
  original_class_key: string;
  corrected_class_key: string | null;
  created_at: string;
}

export function createCorrection(params: CreateCorrectionParams): Promise<{ correction: CorrectionSummary }> {
  return requestJson(`/api/projects/${params.projectId}/corrections`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      observation_id: params.observationId,
      bbox: params.bbox,
      original_class_key: params.originalClassKey,
      original_confidence: params.originalConfidence,
      corrected_class_key: params.correctedClassKey,
    }),
  });
}

export interface ModelVersionMetrics {
  available: boolean;
  train_count?: number;
  test_count?: number;
  accuracy?: number;
  per_class?: { class_key: string; precision: number; recall: number; support: number }[];
  note?: string;
  reason?: string;
}

export type ModelVersionStatus = "candidate" | "production" | "archived";

export interface ModelVersionSummary {
  id: number;
  version_label: string;
  status: ModelVersionStatus;
  status_label_ru: string;
  trained_at: string | null;
  training_sample_count: number;
  metrics: ModelVersionMetrics;
  created_at: string;
}

export interface LearningStatsResponse {
  available: boolean;
  correction_count?: number;
  confirmation_count?: number;
  fixed_error_count?: number;
  not_equipment_count?: number;
  production_version?: ModelVersionSummary | null;
  candidate_versions?: ModelVersionSummary[];
}

export function fetchLearningStats(): Promise<LearningStatsResponse> {
  return requestJson<LearningStatsResponse>("/api/learning/stats");
}

export function fetchModelVersions(): Promise<{ available: boolean; versions: ModelVersionSummary[] }> {
  return requestJson("/api/model-versions");
}

export function trainModelVersion(): Promise<{ started: boolean; reason?: string }> {
  return requestJson("/api/model-versions/train", { method: "POST" });
}

export function deployModelVersion(versionId: number): Promise<{ version: ModelVersionSummary }> {
  return requestJson(`/api/model-versions/${versionId}/deploy`, { method: "POST" });
}
