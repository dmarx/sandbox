#!/usr/bin/env python3
# demo_platform_metadata.py - Demo script for research platform metadata extraction

import json
from loguru import logger
import fire
#!/usr/bin/env python3
# research_platform_metadata.py - Extract metadata from Wikidata for research platforms

import re
import requests
from urllib.parse import urlparse
import sys
from loguru import logger
import fire


def setup_logging():
    """Configure logging with loguru."""
    logger.remove()
    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{function}</cyan>: <level>{message}</level>",
        level="INFO",
    )


def get_domain_from_url(url):
    """Extract the domain from a URL."""
    parsed_url = urlparse(url)
    return parsed_url.netloc


def query_wikidata_for_platform(domain):
    """
    Query Wikidata for information about a research platform based on its domain.
    
    Args:
        domain: Domain name of the research platform (e.g., openreview.net)
        
    Returns:
        Dictionary with platform metadata or None if not found
    """
    # SPARQL query to find items with the given domain
    sparql_query = f"""
    SELECT ?item ?itemLabel ?itemDescription ?website ?identifierProperty ?identifierPropertyLabel
           ?formatterURL ?urlPattern ?formatConstraint
    WHERE {{
      ?item wdt:P856 ?website .  # P856 is the "official website" property
      FILTER(CONTAINS(STR(?website), "{domain}")) .
      
      # Optional: Find identifier properties associated with this item
      OPTIONAL {{
        ?identifierProperty wdt:P1629 ?item .  # P1629 is "item of property"
        OPTIONAL {{ ?identifierProperty wdt:P1630 ?formatterURL }} .  # P1630 is formatter URL
        OPTIONAL {{ ?identifierProperty wdt:P8966 ?urlPattern }} .    # P8966 is URL match pattern
        OPTIONAL {{
          ?identifierProperty p:P2302 ?constraint .  # P2302 is property constraint
          ?constraint ps:P2302 wd:Q21502404 .        # Q21502404 is format constraint
          ?constraint pq:P1793 ?formatConstraint .   # P1793 is format as regex
        }}
      }}
      
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "[AUTO_LANGUAGE],en". }}
    }}
    """
    
    # Execute SPARQL query against Wikidata
    url = "https://query.wikidata.org/sparql"
    try:
        response = requests.get(url, params={"query": sparql_query, "format": "json"})
        response.raise_for_status()
        data = response.json()
        
        if not data.get("results", {}).get("bindings"):
            logger.warning(f"No Wikidata entry found for domain: {domain}")
            return None
            
        # Process and return the results
        results = data["results"]["bindings"]
        platform_data = {
            "domain": domain,
            "wikidata_items": [],
            "identifier_properties": []
        }
        
        # Track processed items to avoid duplicates
        processed_items = set()
        processed_properties = set()
        
        for result in results:
            # Process platform item
            if "item" in result and result["item"]["value"] not in processed_items:
                item_id = result["item"]["value"].split("/")[-1]
                processed_items.add(result["item"]["value"])
                
                platform_item = {
                    "id": item_id,
                    "label": result.get("itemLabel", {}).get("value", "Unknown"),
                    "description": result.get("itemDescription", {}).get("value", ""),
                    "website": result.get("website", {}).get("value", "")
                }
                platform_data["wikidata_items"].append(platform_item)
            
            # Process identifier properties
            if "identifierProperty" in result and result["identifierProperty"]["value"] not in processed_properties:
                prop_id = result["identifierProperty"]["value"].split("/")[-1]
                processed_properties.add(result["identifierProperty"]["value"])
                
                prop_data = {
                    "id": prop_id,
                    "label": result.get("identifierPropertyLabel", {}).get("value", "Unknown"),
                    "formatter_url": result.get("formatterURL", {}).get("value", ""),
                    "url_pattern": result.get("urlPattern", {}).get("value", ""),
                    "format_constraint": result.get("formatConstraint", {}).get("value", "")
                }
                platform_data["identifier_properties"].append(prop_data)
        
        return platform_data
        
    except requests.RequestException as e:
        logger.error(f"Error querying Wikidata: {e}")
        return None


def get_property_details(property_id):
    """
    Get detailed information about a specific Wikidata property.
    
    Args:
        property_id: Wikidata property ID (e.g., P8968)
        
    Returns:
        Dictionary with property metadata
    """
    # Use Wikidata API to get property information
    api_url = "https://www.wikidata.org/w/api.php"
    params = {
        "action": "wbgetentities",
        "format": "json",
        "ids": property_id,
        "props": "labels|descriptions|claims|datatype"
    }
    
    try:
        response = requests.get(api_url, params=params)
        response.raise_for_status()
        data = response.json()
        
        if "entities" not in data or property_id not in data["entities"]:
            logger.error(f"Property {property_id} not found")
            return None
            
        entity = data["entities"][property_id]
        
        # Extract basic information
        property_data = {
            "id": property_id,
            "datatype": entity.get("datatype", ""),
            "labels": {lang: info["value"] for lang, info in entity.get("labels", {}).items()},
            "descriptions": {lang: info["value"] for lang, info in entity.get("descriptions", {}).items()},
            "formatter_url": None,
            "url_pattern": None,
            "format_constraint": None,
            "related_properties": [],
            "applicable_item": None
        }
        
        # Extract claims
        claims = entity.get("claims", {})
        
        # Formatter URL (P1630)
        if "P1630" in claims:
            property_data["formatter_url"] = claims["P1630"][0]["mainsnak"].get("datavalue", {}).get("value", "")
        
        # URL match pattern (P8966)
        if "P8966" in claims:
            property_data["url_pattern"] = claims["P8966"][0]["mainsnak"].get("datavalue", {}).get("value", "")
        
        # Format constraint (part of P2302)
        if "P2302" in claims:
            for constraint in claims["P2302"]:
                if constraint["mainsnak"]["datavalue"]["value"]["id"] == "Q21502404":  # Format constraint
                    for qualifier in constraint.get("qualifiers", {}).get("P1793", []):
                        property_data["format_constraint"] = qualifier["datavalue"]["value"]
                        break
        
        # Related properties (P1659)
        if "P1659" in claims:
            for related in claims["P1659"]:
                related_id = related["mainsnak"]["datavalue"]["value"]["id"]
                property_data["related_properties"].append(related_id)
        
        # Item this property applies to (P1629)
        if "P1629" in claims:
            property_data["applicable_item"] = claims["P1629"][0]["mainsnak"]["datavalue"]["value"]["id"]
        
        return property_data
        
    except requests.RequestException as e:
        logger.error(f"Error querying Wikidata API: {e}")
        return None


def extract_id_from_url(url, id_patterns):
    """
    Extract an identifier from a URL using patterns from Wikidata.
    
    Args:
        url: URL to extract from
        id_patterns: List of dictionaries with regex patterns and property IDs
        
    Returns:
        Dictionary with extracted IDs and their property IDs
    """
    extracted_ids = {}
    
    for pattern_info in id_patterns:
        if not pattern_info.get("url_pattern"):
            continue
            
        try:
            pattern = pattern_info["url_pattern"]
            # If pattern uses Wikidata's capture group syntax, extract the ID
            match = re.search(pattern, url)
            if match and match.groups():
                extracted_ids[pattern_info["id"]] = {
                    "id": match.group(1),
                    "property": pattern_info
                }
        except re.error:
            logger.warning(f"Invalid regex pattern: {pattern}")
    
    return extracted_ids


def analyze_research_platform(url, property_id=None):
    """
    Analyze a research platform URL and extract metadata from Wikidata.
    
    Args:
        url: URL of a research platform page
        property_id: Optional Wikidata property ID to use for extraction
        
    Returns:
        Dictionary with platform metadata and extracted identifiers
    """
    setup_logging()
    
    domain = get_domain_from_url(url)
    logger.info(f"Analyzing research platform at domain: {domain}")
    
    # Get platform metadata from Wikidata
    platform_data = query_wikidata_for_platform(domain)
    
    if not platform_data:
        logger.warning(f"No metadata found for {domain} in Wikidata")
        return None
    
    # If a specific property ID was provided, get its details
    if property_id:
        prop_details = get_property_details(property_id)
        if prop_details:
            logger.info(f"Found property details for {property_id}: {prop_details['labels'].get('en', '')}")
            # Add to platform data if not already there
            existing_ids = [p["id"] for p in platform_data["identifier_properties"]]
            if property_id not in existing_ids:
                platform_data["identifier_properties"].append(prop_details)
    
    # Extract identifiers from URL
    id_patterns = [
        {
            "id": prop["id"],
            "url_pattern": prop["url_pattern"],
            "formatter_url": prop["formatter_url"]
        }
        for prop in platform_data["identifier_properties"]
        if prop["url_pattern"]
    ]
    
    extracted_ids = extract_id_from_url(url, id_patterns)
    platform_data["extracted_ids"] = extracted_ids
    
    # Generate formatter URLs for extracted IDs
    platform_data["formatted_urls"] = {}
    for prop_id, id_info in extracted_ids.items():
        if id_info["property"]["formatter_url"]:
            formatted_url = id_info["property"]["formatter_url"].replace("$1", id_info["id"])
            platform_data["formatted_urls"][prop_id] = formatted_url
    
    return platform_data


def main(url, property_id=None):
    """
    Main function to analyze a research platform URL.
    
    Args:
        url: URL of a research platform page
        property_id: Optional Wikidata property ID to use for extraction
    """
    result = analyze_research_platform(url, property_id)
    
    if result:
        # Print summary
        logger.info(f"\nAnalysis Results for URL: {url}")
        
        if result["wikidata_items"]:
            logger.info("\nResearch Platform Information:")
            for item in result["wikidata_items"]:
                logger.info(f"  - {item['label']} ({item['id']}): {item['description']}")
        
        if result["identifier_properties"]:
            logger.info("\nIdentifier Properties:")
            for prop in result["identifier_properties"]:
                logger.info(f"  - {prop['label']} ({prop['id']})")
                if prop["formatter_url"]:
                    logger.info(f"    Formatter URL: {prop['formatter_url']}")
                if prop["url_pattern"]:
                    logger.info(f"    URL Pattern: {prop['url_pattern']}")
                if prop["format_constraint"]:
                    logger.info(f"    Format Constraint: {prop['format_constraint']}")
        
        if result["extracted_ids"]:
            logger.info("\nExtracted Identifiers:")
            for prop_id, id_info in result["extracted_ids"].items():
                logger.info(f"  - {prop_id}: {id_info['id']}")
                if prop_id in result["formatted_urls"]:
                    logger.info(f"    Formatted URL: {result['formatted_urls'][prop_id]}")
        else:
            logger.warning("No identifiers could be extracted from the URL")
    
    return result


# if __name__ == "__main__":
#     fire.Fire(main)


def demonstrate_openreview():
    """Demonstrate metadata extraction for OpenReview."""
    # Sample URL from OpenReview
    url = "https://openreview.net/forum?id=et5l9qPUhm"
    property_id = "P8968"  # OpenReview.net submission ID
    
    logger.info("=" * 80)
    logger.info("DEMONSTRATING OPENREVIEW METADATA EXTRACTION")
    logger.info("=" * 80)
    
    result = analyze_research_platform(url, property_id)
    
    # Pretty print the complete result
    logger.info("\nComplete metadata (JSON):")
    print(json.dumps(result, indent=2))
    
    logger.info("\nExample of how to use this data programmatically:")
    if result and result["extracted_ids"] and property_id in result["extracted_ids"]:
        id_value = result["extracted_ids"][property_id]["id"]
        logger.info(f"Extracted OpenReview ID: {id_value}")
        
        # Demonstrate validation against format constraint
        if result["identifier_properties"]:
            for prop in result["identifier_properties"]:
                if prop["id"] == property_id and prop["format_constraint"]:
                    import re
                    pattern = prop["format_constraint"]
                    is_valid = bool(re.match(f"^{pattern}$", id_value))
                    logger.info(f"ID validation against format constraint: {is_valid}")
    
    return result


def demonstrate_arxiv():
    """Demonstrate metadata extraction for arXiv."""
    # Sample URL from arXiv
    url = "https://arxiv.org/abs/2310.06825"
    property_id = "P818"  # arXiv ID
    
    logger.info("\n" + "=" * 80)
    logger.info("DEMONSTRATING ARXIV METADATA EXTRACTION")
    logger.info("=" * 80)
    
    result = analyze_research_platform(url, property_id)
    
    # Show how to use the extracted arXiv ID
    if result and result["extracted_ids"] and property_id in result["extracted_ids"]:
        arxiv_id = result["extracted_ids"][property_id]["id"]
        logger.info(f"\nExtracted arXiv ID: {arxiv_id}")
        
        # Show how to access arXiv API with this ID
        logger.info("\nExample of using this ID with arXiv API:")
        api_url = f"http://export.arxiv.org/api/query?id_list={arxiv_id}"
        logger.info(f"API URL: {api_url}")
    
    return result


def demonstrate_doi():
    """Demonstrate metadata extraction for DOI-based platforms."""
    # Sample URL with a DOI
    url = "https://doi.org/10.1038/s41586-021-03819-2"
    property_id = "P356"  # DOI
    
    logger.info("\n" + "=" * 80)
    logger.info("DEMONSTRATING DOI METADATA EXTRACTION")
    logger.info("=" * 80)
    
    result = analyze_research_platform(url, property_id)
    
    # Show how to use the extracted DOI
    if result and result["extracted_ids"] and property_id in result["extracted_ids"]:
        doi = result["extracted_ids"][property_id]["id"]
        logger.info(f"\nExtracted DOI: {doi}")
        
        # Show how to use this with CrossRef API
        logger.info("\nExample of using this DOI with CrossRef API:")
        api_url = f"https://api.crossref.org/works/{doi}"
        logger.info(f"API URL: {api_url}")
    
    return result


def demonstrate_custom():
    """Demonstrate custom platform analysis."""
    # User can input their own URL and optional property ID
    logger.info("\n" + "=" * 80)
    logger.info("CUSTOM PLATFORM ANALYSIS")
    logger.info("=" * 80)
    
    url = input("Enter research platform URL: ")
    property_id = input("Enter Wikidata property ID (optional, press Enter to skip): ").strip() or None
    
    if property_id and not property_id.startswith('P'):
        logger.warning("Property ID should start with 'P' (e.g., P8968)")
        property_id = 'P' + property_id if property_id.isdigit() else None
    
    result = analyze_research_platform(url, property_id)
    return result


def main(mode="all", url=None, property_id=None):
    """
    Run demonstration of research platform metadata extraction.
    
    Args:
        mode: One of "all", "openreview", "arxiv", "doi", "custom", or "url"
        url: URL to analyze if mode is "url"
        property_id: Optional Wikidata property ID to use for extraction
    """
    if mode == "all":
        demonstrate_openreview()
        demonstrate_arxiv()
        demonstrate_doi()
    elif mode == "openreview":
        demonstrate_openreview()
    elif mode == "arxiv":
        demonstrate_arxiv()
    elif mode == "doi":
        demonstrate_doi()
    elif mode == "custom":
        demonstrate_custom()
    elif mode == "url" and url:
        analyze_research_platform(url, property_id)
    else:
        logger.error(f"Invalid mode: {mode}")
        logger.info("Available modes: all, openreview, arxiv, doi, custom, url")


if __name__ == "__main__":
    fire.Fire(main)
