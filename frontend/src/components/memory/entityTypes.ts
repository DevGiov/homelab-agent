import { Building2, FolderKanban, MapPin, Package, Server, Tag, User, type LucideIcon } from 'lucide-react';
import type { EntityType } from '../../api/memory';

export const ENTITY_TYPE_INFO: Record<EntityType, { label: string; icon: LucideIcon }> = {
  person: { label: 'Persona', icon: User },
  organization: { label: 'Organizzazione', icon: Building2 },
  place: { label: 'Luogo', icon: MapPin },
  project: { label: 'Progetto', icon: FolderKanban },
  software: { label: 'Software', icon: Package },
  infrastructure: { label: 'Infrastruttura', icon: Server },
  other: { label: 'Altro', icon: Tag },
};
