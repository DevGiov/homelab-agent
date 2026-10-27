import { http } from './http';

export interface AutomationArtifact {
  artifact_id: string;
  run_id: string;
  step_run_id?: string | null;
  name: string;
  title?: string;
  type: string;
  mime_type?: string;
  storage_uri: string;
  is_preserved?: boolean;
  is_favorite?: boolean;
  content?: string;
  created_at: string;
  automation_id?: string;
  automation_name?: string;
  run_status?: string;
}

const artifactPath = (artifactId: string) => `/automations/artifacts/${artifactId}`;

export function fetchAllArtifacts(params?: {
  automation_id?: string;
  query?: string;
  favorite_only?: boolean;
  preserved_only?: boolean;
  limit?: number;
}): Promise<AutomationArtifact[]> {
  return http.get('/automations/artifacts', {
    automation_id: params?.automation_id || undefined,
    query: params?.query || undefined,
    favorite_only: params?.favorite_only ? true : undefined,
    preserved_only: params?.preserved_only ? true : undefined,
    limit: params?.limit || 100,
  });
}

export function getArtifactDetails(artifactId: string): Promise<AutomationArtifact> {
  return http.get(artifactPath(artifactId));
}

export function toggleArtifactFavorite(artifactId: string): Promise<{ artifact_id: string; is_favorite: boolean }> {
  return http.patch(`${artifactPath(artifactId)}/favorite`);
}

export function toggleArtifactPreserve(artifactId: string): Promise<{ artifact_id: string; is_preserved: boolean }> {
  return http.patch(`${artifactPath(artifactId)}/preserve`);
}

export function deleteArtifact(artifactId: string): Promise<{ deleted: boolean; artifact_id: string }> {
  return http.delete(artifactPath(artifactId));
}
