import { useCallback, useEffect, useState } from 'react';
import { getModelCatalog, type CatalogProvider, type ModelCatalogResponse, type ModelDetail, type ModelRef } from '../api/providers';

const VISION_NAME = /qwen3\.6|vl|vision|llava|pixtral|gemma-4/i;

const NO_DETAILS: ModelDetail[] = [];

/**
 * Catalogo dei modelli per i selettori: i provider attivi, ognuno con i suoi modelli, e la scelta di partenza (`defaultModel`,
 * la coppia provider e modello di una conversazione nuova). `modelDetails` e `loadedModel` sono quelli del provider
 * predefinito, per i lavori in background che non scelgono un provider.
 */
export function useModelCatalog() {
  const [catalog, setCatalog] = useState<ModelCatalogResponse | null>(null);

  const refreshModels = useCallback(async () => {
    try {
      setCatalog(await getModelCatalog());
    } catch (err) {
      console.warn('Modelli della chat non caricati:', err);
    }
  }, []);

  useEffect(() => {
    refreshModels();
  }, [refreshModels]);

  const providers: CatalogProvider[] = catalog?.providers ?? [];
  const defaultModel: ModelRef | null = catalog?.default ?? null;
  const modelDetails = providers.find((p) => p.name === defaultModel?.provider)?.models ?? NO_DETAILS;

  const isVisionModel = (ref: ModelRef) =>
    providers.find((p) => p.name === ref.provider)?.models.find((m) => m.id === ref.model)?.is_vision ?? VISION_NAME.test(ref.model);

  const loadedModel = modelDetails.find((d) => d.is_loaded)?.id ?? null;

  return { providers, defaultModel, modelDetails, loadedModel, refreshModels, isVisionModel };
}

export type ModelCatalog = ReturnType<typeof useModelCatalog>;
