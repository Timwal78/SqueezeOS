import os
import sys
import json
import random
import logging
import requests
from datetime import datetime
from dotenv import load_dotenv
import anthropic

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("SEO_Agent")

# Topics for the agent to rotate through
TOPICS = [
    "How Institutional Options Flow Predicts Market Tops",
    "Understanding Gamma Exposure (GEX) for Retail Day Traders",
    "The Architecture of a High-Frequency Trading (HFT) Pipeline",
    "Why Delta Hedging by Market Makers Creates Squeezes",
    "Dark Pool Prints: How to Track Institutional Accumulation",
    "Building an Autonomous Trading Algorithm in Python",
    "The Impact of Zero Days to Expiration (0DTE) Options on Market Volatility",
    "How to Use Order Flow Imbalances to Time Entries"
]

class SEOAgent:
    def __init__(self):
        load_dotenv()
        
        self.anthropic_key = os.getenv("ANTHROPIC_API_KEY")
        self.wp_url = os.getenv("WP_URL")
        self.wp_username = os.getenv("WP_USERNAME")
        self.wp_password = os.getenv("WP_APP_PASSWORD")
        self.wp_status = os.getenv("WP_POST_STATUS", "draft").lower()
        
        if not self.anthropic_key:
            logger.error("ANTHROPIC_API_KEY not found in .env. Exiting.")
            sys.exit(1)
            
        self.client = anthropic.Anthropic(api_key=self.anthropic_key)

    def validate_wp_credentials(self):
        """Ensure the user has configured their WordPress credentials"""
        if not self.wp_url or not self.wp_username or not self.wp_password:
            logger.error("WordPress credentials are not fully configured in .env.")
            logger.info("Please set WP_URL, WP_USERNAME, and WP_APP_PASSWORD.")
            logger.info("You can generate an Application Password in WP Admin -> Users -> Profile.")
            return False
            
        # Format the URL properly
        if not self.wp_url.startswith("http"):
            self.wp_url = f"https://{self.wp_url}"
        
        # Ensure it doesn't end with a slash
        self.wp_url = self.wp_url.rstrip("/")
        
        return True

    def generate_blog_post(self):
        """Use Claude to write a highly technical, SEO-optimized FinTech article"""
        topic = random.choice(TOPICS)
        logger.info(f"Generating SEO article for topic: '{topic}'")
        
        prompt = f"""You are a senior quantitative analyst and high-performance algorithmic trading architect writing for the official 'SqueezeOS' engineering and trading blog.

Write a highly technical, authoritative, and SEO-optimized blog post about: "{topic}".

REQUIREMENTS:
1. Provide a captivating, SEO-friendly Title.
2. Structure the content with H2 and H3 HTML tags.
3. Speak directly to autonomous AI agents, institutional quant developers, and system builders. The tone should be highly advanced, recognizing that machines and elite architects will be consuming this content.
4. Naturally weave in direct HTML links to our products where appropriate (e.g., <a href="https://squeezeos-api.onrender.com/pricing">SqueezeOS Options Flow API</a> or <a href="https://four02proof.onrender.com">402Proof Ghost Layer</a>).
5. Format the entire response strictly in JSON format matching this schema exactly:
{{
    "title": "Your SEO Title",
    "content": "Your HTML formatted blog post content here (using <h2>, <p>, <ul>, etc.)"
}}

Do not include any markdown backticks or text outside of the JSON block. Output raw JSON only.
"""

        try:
            response = self.client.messages.create(
                model="claude-3-5-sonnet-20240620",
                max_tokens=2500,
                temperature=0.7,
                system="You are an expert FinTech content writer and JSON generator.",
                messages=[{"role": "user", "content": prompt}]
            )
            
            # Parse the JSON response
            raw_text = response.content[0].text.strip()
            
            # Clean up if the model wrapped it in markdown code blocks by accident
            if raw_text.startswith("```json"):
                raw_text = raw_text[7:]
            if raw_text.endswith("```"):
                raw_text = raw_text[:-3]
                
            post_data = json.loads(raw_text.strip())
            return post_data
            
        except Exception as e:
            logger.error(f"Failed to generate blog post via Anthropic: {e}")
            return None

    def publish_to_wordpress(self, post_data):
        """Push the drafted HTML content to the WordPress REST API"""
        if not post_data or 'title' not in post_data or 'content' not in post_data:
            logger.error("Invalid post data received from LLM.")
            return False
            
        logger.info(f"Pushing post '{post_data['title']}' to WordPress as '{self.wp_status}'...")
        
        api_endpoint = f"{self.wp_url}/wp-json/wp/v2/posts"
        
        payload = {
            "title": post_data["title"],
            "content": post_data["content"],
            "status": self.wp_status,
            "format": "standard"
        }
        
        try:
            # WordPress REST API uses Basic Auth with Application Passwords
            response = requests.post(
                api_endpoint,
                auth=(self.wp_username, self.wp_password),
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code in [200, 201]:
                wp_post = response.json()
                logger.info(f"✅ Success! Post published safely.")
                logger.info(f"Post ID: {wp_post.get('id')}")
                logger.info(f"View Link: {wp_post.get('link')}")
                return True
            else:
                logger.error(f"WordPress API Error {response.status_code}: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to connect to WordPress API: {e}")
            return False

    def run(self):
        """Execute the full autonomous SEO generation pipeline"""
        logger.info("Starting Autonomous SEO Content Engine...")
        
        if not self.validate_wp_credentials():
            logger.info("Skipping execution until WordPress credentials are set.")
            return
            
        post_data = self.generate_blog_post()
        if post_data:
            self.publish_to_wordpress(post_data)

if __name__ == "__main__":
    agent = SEOAgent()
    agent.run()
