// Card dispatcher — picks the right card component for the card_type
// the chat backend emitted. Unknown types render as a JSON pre-block so
// nothing is silently dropped.

import type { ChatCard } from '../../../api/seoTypes';
import CompetitorDeltaCard from './CompetitorDeltaCard';
import CrawlerSummaryCard from './CrawlerSummaryCard';
import FindingCard from './FindingCard';
import GscTopQueriesCard from './GscTopQueriesCard';
import KeywordOpportunityCard from './KeywordOpportunityCard';

export default function CardRenderer({ card }: { card: ChatCard }) {
  switch (card.card_type) {
    case 'gsc_top_queries':
      return <GscTopQueriesCard payload={card.payload} />;
    case 'keyword_opportunities':
      return <KeywordOpportunityCard payload={card.payload} />;
    case 'competitor_delta':
      return <CompetitorDeltaCard payload={card.payload} />;
    case 'crawler_summary':
      return <CrawlerSummaryCard payload={card.payload} />;
    case 'finding':
      return <FindingCard payload={card.payload} />;
    default:
      return (
        <div className="seo-card chat-card chat-card-unknown">
          <div className="chat-card-title">Card: {card.card_type}</div>
          <pre>{JSON.stringify(card.payload, null, 2)}</pre>
        </div>
      );
  }
}
