// useCompetitorGap — fetches the per-agent detection findings for the
// latest completed grade run on a domain. Surfaces both the findings
// and the per-agent skip / crash audit so the UI can show "API key not
// configured" rather than "no findings".

import { useQuery } from '@tanstack/react-query';
import { api } from '../client';
import type { CompetitorGapResponse } from '../seoTypes';

const DEFAULT_DOMAIN = 'bajajlifeinsurance.com';

export function useCompetitorGap(domain: string = DEFAULT_DOMAIN) {
  return useQuery({
    queryKey: ['seo', 'competitor', 'gap', domain],
    queryFn: () =>
      api.get<CompetitorGapResponse>('/seo/competitor/gap/', { domain }),
    staleTime: 5 * 60 * 1000,
  });
}
