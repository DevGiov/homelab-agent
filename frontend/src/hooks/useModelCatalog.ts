import { useCallback, useEffect, useState } from 'react';
import { getProviderModelsWithDetails, getProviders, type ModelDetail } from '../api/providers';

const VISION_NAME = /qwen3\.6|vl|vision|llava|pixtral|gemma-4/i;

/** Modelli del provider attivo, per i selettori della chat. */
export function useModelCatalog() {
  const [activeProvider, setActiveProvider] = useState('llamacpp');
  const [modelDetails, setModelDetails] = useState<ModelDetail[]>([]);

  const refreshModels = useCallback(async () => {
    try {
      const { active_provider } = await getProviders();
      if (!active_provider) return;
      setActiveProvider(active_provider);
      setModelDetails(await getProviderModelsWithDetails(active_provider));
    } catch (err) {
      console.warn('Modelli della chat non caricati:', err);
    }
  }, []);

  useEffect(() => {
    refreshModels();
  }, [refreshModels]);

  const isVisionModel = (modelId: string) =>
    modelDetails.find((d) => d.id === modelId)?.is_vision ?? VISION_NAME.test(modelId);

  return { activeProvider, modelDetails, refreshModels, isVisionModel };
}

export type ModelCatalog = ReturnType<typeof useModelCatalog>;
