import { PROMPT_VERSION, seasonForMonth } from '@meal-planner/engine';

import { ScreenPlaceholder } from '@/components/screen-placeholder';

export default function PlanScreen() {
  const season = seasonForMonth(new Date().getMonth() + 1, 'northern');
  return (
    <ScreenPlaceholder
      title="This Week"
      body={`Weekly plan lands here (Phase 2): manual picks with allergen shields and variety warnings, or AI planning with your own Anthropic key. Current season: ${season}. Engine prompts: ${PROMPT_VERSION}.`}
    />
  );
}
