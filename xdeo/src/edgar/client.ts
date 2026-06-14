// SEC EDGAR API client. All endpoints are free and require no auth — SEC only
// asks for a descriptive User-Agent (EDGAR_USER_AGENT). Docs:
//   https://www.sec.gov/search-filings/edgar-application-programming-interfaces
//
// NOTE: SEC rate-limits to ~10 req/s per IP. On Workers we additionally cache
// the ticker->CIK map and use conditional requests where possible.

const DATA_HOST = "https://data.sec.gov";
const WWW_HOST = "https://www.sec.gov";

export interface RecentFilings {
  accessionNumber: string[];
  form: string[];
  filingDate: string[];
  reportDate: string[];
  primaryDocument: string[];
  acceptanceDateTime: string[];
}

export interface SubmissionsDoc {
  cik: string;
  name: string;
  tickers?: string[];
  filings: { recent: RecentFilings };
}

/** A single XBRL fact from the companyconcept API. */
export interface XbrlFact {
  end: string; // period end "YYYY-MM-DD"
  val: number;
  fy: number | null;
  fp: string | null; // "Q1".."Q4" | "FY"
  form: string; // "10-K" | "10-Q" | ...
  filed: string; // "YYYY-MM-DD"
  accn: string; // accession number with dashes
  frame?: string;
}

export class EdgarClient {
  constructor(private readonly userAgent: string) {}

  private async getJson<T>(url: string): Promise<T | null> {
    const res = await fetch(url, {
      headers: {
        // SEC requires a descriptive UA or returns 403.
        "User-Agent": this.userAgent,
        "Accept-Encoding": "gzip, deflate",
        Accept: "application/json"
      },
      // Edge cache: filings are immutable once filed; submissions update slowly.
      cf: { cacheTtl: 300, cacheEverything: true }
    });
    if (res.status === 404) return null;
    if (!res.ok) {
      throw new Error(`EDGAR ${res.status} for ${url}`);
    }
    return (await res.json()) as T;
  }

  /** zero-pad a CIK to the 10-digit form EDGAR's data API expects. */
  static padCik(cik: string | number): string {
    return String(cik).replace(/\D/g, "").padStart(10, "0");
  }

  /** company_tickers.json: { "0": { cik_str, ticker, title }, ... } */
  async tickerMap(): Promise<Record<string, { cik: string; name: string }>> {
    const raw = await this.getJson<
      Record<string, { cik_str: number; ticker: string; title: string }>
    >(`${WWW_HOST}/files/company_tickers.json`);
    const out: Record<string, { cik: string; name: string }> = {};
    if (!raw) return out;
    for (const k of Object.keys(raw)) {
      const row = raw[k]!;
      out[row.ticker.toUpperCase()] = {
        cik: EdgarClient.padCik(row.cik_str),
        name: row.title
      };
    }
    return out;
  }

  /** Recent filings + company metadata for a CIK. */
  submissions(cik: string): Promise<SubmissionsDoc | null> {
    return this.getJson<SubmissionsDoc>(
      `${DATA_HOST}/submissions/CIK${EdgarClient.padCik(cik)}.json`
    );
  }

  /**
   * All reported values for one us-gaap concept (e.g. EarningsPerShareDiluted).
   * Returns the flattened fact list across all unit types.
   */
  async concept(
    cik: string,
    tag: string,
    taxonomy = "us-gaap"
  ): Promise<XbrlFact[]> {
    const doc = await this.getJson<{
      units: Record<string, XbrlFact[]>;
    }>(
      `${DATA_HOST}/api/xbrl/companyconcept/CIK${EdgarClient.padCik(
        cik
      )}/${taxonomy}/${tag}.json`
    );
    if (!doc?.units) return [];
    return Object.values(doc.units).flat();
  }
}
