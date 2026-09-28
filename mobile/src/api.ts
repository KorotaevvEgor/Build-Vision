// Клиент backend API для мобильного приложения — те же эндпоинты, что и у
// веб-фронтенда (frontend/src/api.ts). Базовый URL — VITE_API_BASE_URL (обязателен,
// см. .env.example) — мобильное приложение грузится не с origin сайта, поэтому абсолютный адрес нужен всегда.

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "https://your-domain.example";

export type DeviationStatus = "no_deviation" | "possible_deviation" | "insufficient_data";

export class ApiError extends Error {
  status: number;
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
    headers.set("X-BuildVision-Request", "1");
  }
  // credentials: "include" — сессия через cookie Django (см. backend/app/auth.py).
  // В WebView Capacitor это опирается на нативный cookie jar; см. mobile/README.md
  // про известный риск с кросс-доменными cookie и запасной вариант (bearer-токен).
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

// --- Авторизация и аккаунт ---

export type UserRole = "admin" | "participant";

export interface CurrentUser {
  id: number;
  username: string;
  full_name: string;
  role: UserRole;
  role_label: string;
  position: string;
  display_position: string;
  avatar_url: string | null;
  date_joined: string;
  last_login: string | null;
}

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

// --- Проекты ---

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

export interface AssignableUser {
  id: number;
  username: string;
  full_name: string;
}

export function fetchAssignableUsers(): Promise<{ users: AssignableUser[] }> {
  return requestJson("/api/projects/assignable-users");
}

export interface CreateProjectParams {
  name: string;
  address: string;
  status: ProjectStatus;
  latitude: number | null;
  longitude: number | null;
  memberUserIds: number[];
}

export function createProject(params: CreateProjectParams): Promise<{ project: ProjectSummary }> {
  return requestJson("/api/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: params.name,
      address: params.address,
      status: params.status,
      latitude: params.latitude,
      longitude: params.longitude,
      member_user_ids: params.memberUserIds,
    }),
  });
}

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

export function fetchSite(projectId: ProjectId): Promise<SiteResponse> {
  return requestJson<SiteResponse>(`/api/projects/${projectId}/site`);
}

// --- Детекции / наблюдения ---

export type DetectionActivity = "working" | "idle" | "unknown";
export type FrameZoneKind = "work" | "parking" | "entrance" | "danger" | "uncontrolled";

export interface Detection {
  class_key: string;
  label_ru: string;
  in_taxonomy: boolean;
  confidence: number;
  bbox: [number, number, number, number];
  ambiguous: boolean;
  runner_up_class_key?: string | null;
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
  is_critical?: boolean;
  required: string[];
  allowed: string[];
  quantity_checks: QuantityCheck[];
  missing_required: string[];
  explanation_ru: string;
  unexpected_detections: Detection[];
  ambiguous_detections: Detection[];
}

export interface ObservationResponse {
  observation_id: string;
  saved_to_db: boolean;
  zone_id: string;
  overall_status: DeviationStatus;
  overall_status_label_ru: string;
  overall_explanation_ru: string;
  stages: StageEvaluationResponse[];
  detections: Detection[];
}

export interface CreateObservationParams {
  projectId: ProjectId;
  zoneId: string;
  observedDate?: string;
  dateConfirmed: boolean;
  cameraId?: string;
  image: Blob;
  fileName: string;
}

export async function createObservation(params: CreateObservationParams): Promise<ObservationResponse> {
  const formData = new FormData();
  formData.set("zone_id", params.zoneId);
  formData.set("date_confirmed", String(params.dateConfirmed));
  if (params.observedDate) {
    formData.set("observed_date", params.observedDate);
  }
  if (params.cameraId) {
    formData.set("camera_id", params.cameraId);
  }
  formData.set("image", params.image, params.fileName);

  return requestJson<ObservationResponse>(`/api/projects/${params.projectId}/observations`, {
    method: "POST",
    body: formData,
  });
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

export function getObservationImageUrl(projectId: ProjectId, observationId: string): string {
  return `${API_BASE_URL}/api/projects/${projectId}/observations/${observationId}/image`;
}

// --- Главная / камеры ---

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

export interface ZoneStageOnDate {
  stage_id: string;
  work_name: string;
  start_date: string;
  end_date: string;
  rule: { required: string[]; allowed: string[] } | null;
}

/** Этапы зоны на указанную дату — для просмотра истории кадров камеры. */
export function fetchZoneStagesOnDate(
  projectId: ProjectId,
  zoneId: string,
  onDate?: string,
): Promise<{ zone_id: string; stages: ZoneStageOnDate[] }> {
  return requestJson(`/api/projects/${projectId}/zones/${zoneId}/stages${onDate ? `?on_date=${onDate}` : ""}`);
}

export function fetchNotifications(
  projectId: ProjectId,
  limit = 20,
): Promise<{ available: boolean; items: NotificationItem[] }> {
  return requestJson(`/api/projects/${projectId}/notifications?limit=${limit}`);
}

// --- Зоны площадки (только чтение на мобильном — редактирование в веб-версии) ---

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

// --- Календарный план: сетевой график, правила, этапы (CRUD только администратор) ---

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
  total_float_days: number;
  is_critical: boolean;
  projected_finish_date: string;
  state: StageState | "";
  state_label_ru: string;
  delay_days: number;
  observation_count: number;
  compliance_percent: number | null;
  reason: string;
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

export function fetchRules(projectId: ProjectId): Promise<RulesResponse> {
  return requestJson<RulesResponse>(`/api/projects/${projectId}/rules`);
}

export interface VocabularyClassSummary {
  key: string;
  label_ru: string;
}

export function fetchVocabulary(): Promise<{ classes: VocabularyClassSummary[] }> {
  return requestJson("/api/vocabulary");
}

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

/** Точка фактической готовности: один обход, усреднённый по ракурсам. */
export interface ReadinessPoint {
  date: string;
  readiness_percent: number;
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

export interface AnalyticsResponse {
  available: boolean;
  deviations_by_day: { date: string; count: number }[];
  equipment_counts: { class_key: string; label_ru: string; count: number }[];
  total_observations: number;
}

export function fetchAnalytics(projectId: ProjectId, days = 14): Promise<AnalyticsResponse> {
  return requestJson<AnalyticsResponse>(`/api/projects/${projectId}/analytics?days=${days}`);
}

// --- Отклонения (жизненный цикл) и лента событий ---

export type DeviationLifecycleStatus = "detected" | "assigned" | "resolved" | "confirmed" | "dismissed";

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
  before_observation_id: string | null;
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

// --- Настройки ---

export type VlmConfidenceLevel = "high" | "medium" | "low";

export interface AppSettings {
  detector_confidence: number;
  autolabel_min_vlm_confidence: VlmConfidenceLevel;
  ambiguity_margin: number;
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
