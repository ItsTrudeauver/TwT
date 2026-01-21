import aiohttp
import asyncio
import json
import os
import time

# Configuration
OUTPUT_FILE = "data/rankings.json"
MAX_PAGES = 200  # 50 chars/page * 200 pages = 10,000 Characters
ANILIST_URL = "https://graphql.anilist.co"

QUERY = """
query ($page: Int) {
    Page(page: $page, perPage: 50) {
        pageInfo { hasNextPage }
        characters(sort: FAVOURITES_DESC) {
            id
            name { full }
            favourites
        }
    }
}
"""

async def fetch_page(session, page):
    try:
        async with session.post(ANILIST_URL, json={'query': QUERY, 'variables': {'page': page}}) as resp:
            if resp.status == 429:
                print(f"⏳ Rate Limit hit on page {page}. Waiting 60s...")
                await asyncio.sleep(60)
                return await fetch_page(session, page)
            if resp.status != 200:
                print(f"❌ Error on page {page}: {resp.status}")
                return []
            
            data = await resp.json()
            return data['data']['Page']['characters']
    except Exception as e:
        print(f"⚠️ Exception on page {page}: {e}")
        return []

async def main():
    if not os.path.exists("data"):
        os.makedirs("data")

    print(f"🚀 Starting Scrape of Top {MAX_PAGES * 50} Characters...")
    
    rank_map = {}
    current_rank = 1
    
    async with aiohttp.ClientSession() as session:
        for page in range(1, MAX_PAGES + 1):
            chars = await fetch_page(session, page)
            if not chars: break
            
            for char in chars:
                # Map ID -> Rank
                rank_map[str(char['id'])] = current_rank
                current_rank += 1
            
            print(f"✅ Indexed Page {page}/{MAX_PAGES} (Rank {current_rank-1})")
            
            # Be nice to API (0.8s delay prevents 90req/min limit)
            await asyncio.sleep(0.8)

    with open(OUTPUT_FILE, "w") as f:
        json.dump(rank_map, f)
    
    print(f"🎉 Done! Saved {len(rank_map)} rankings to {OUTPUT_FILE}")

if __name__ == "__main__":
    asyncio.run(main())