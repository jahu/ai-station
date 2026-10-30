export type SpeechDelivery = {
  exaggeration: number;
  cfg_weight: number;
  temperature: number;
};

export const defaultSpeechDelivery: SpeechDelivery = {
  exaggeration: 0.8,
  cfg_weight: 0.4,
  temperature: 0.6,
};
