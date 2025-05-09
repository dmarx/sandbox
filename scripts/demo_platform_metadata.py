#!/usr/bin/env python3
# improved_platform_metadata.py - Improved approach to extract metadata from Wikidata

import re
import requests
from urllib.parse import urlparse
import sys
from loguru import logger
import fire
import time


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


def find_platform_in_wikidata(domain):
    """
    Find platform items in Wikidata based on domain.
    Uses a simpler, more targeted SPARQL query.
    
    Args:
        domain: Domain name of the research platform (e.g., openreview.net)
        
    Returns:
        List of platform items (dicts) or None if not found
    """
    # Simpler SPARQL query focused just on finding platform items
    sparql_query = f"""
    SELECT ?item ?itemLabel ?itemDescription ?website
    WHERE {{
      ?item wdt:P856 ?website .  # P856 is the "official website" property
      FILTER(CONTAINS(STR(?website), "{domain}")) .
      
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "[AUTO_LANGUAGE],en". }}
    }}
    LIMIT 10
    """
    
    # Execute SPARQL query against Wikidata
    url = "https://query.wikidata.org/sparql"
    try:
        response = requests.get(url, params={"query": sparql_query, "format": "json"})
        response.raise_for_status()
        data = response.json()
        
        if not data.get("results", {}).get("bindings"):
            logger.warning(f"No Wikidata items found for domain: {domain}")
            return None
            
        # Process and return the results
        results = data["results"]["bindings"]
        platform_items = []
        
        for result in results:
            if "item" in result:
                item_id = result["item"]["value"].split("/")[-1]
                platform_item = {
                    "id": item_id,
                    "label": result.get("itemLabel", {}).get("value", "Unknown"),
                    "description": result.get("itemDescription", {}).get("value", ""),
                    "website": result.get("website", {}).get("value", "")
                }
                platform_items.append(platform_item)
        
        return platform_items
        
    except requests.RequestException as e:
        logger.error(f"Error querying Wikidata SPARQL endpoint: {e}")
        return None


def find_identifier_properties(item_id):
    """
    Find identifier properties associated with a Wikidata item.
    Uses direct API calls rather than complex SPARQL queries.
    
    Args:
        item_id: Wikidata item ID (e.g., Q56476926)
        
    Returns:
        List of property IDs or None if none found
    """
    # Use Wikidata API to find properties that have this item as their "item of property"
    api_url = "https://www.wikidata.org/w/api.php"
    params = {
        "action": "query",
        "format": "json",
        "list": "backlinks",
        "bltitle": f"Item:{item_id}",
        "blnamespace": 120,  # Property namespace
        "bllimit": 50
    }
    
    try:
        logger.info(f"Finding identifier properties for item {item_id}")
        response = requests.get(api_url, params=params)
        response.raise_for_status()
        data = response.json()
        
        properties = []
        for backlink in data.get("query", {}).get("backlinks", []):
            # Extract property ID from title (format: "Property:PXXXX")
            prop_id = backlink["title"].split(":")[-1]
            properties.append(prop_id)
        
        if not properties:
            logger.warning(f"No properties found linking to item {item_id}")
            
        return properties
    
    except requests.RequestException as e:
        logger.error(f"Error querying Wikidata API for properties: {e}")
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
        
        # Get human-readable label
        property_data["label"] = property_data["labels"].get("en", property_id)
        
        logger.info(f"Found property details for {property_id}: {property_data['label']}")
        return property_data
        
    except requests.RequestException as e:
        logger.error(f"Error querying Wikidata API for property details: {e}")
        return None


def extract_id_from_url(url, property_details):
    """
    Extract an identifier from a URL using patterns from a property.
    
    Args:
        url: URL to extract from
        property_details: Dictionary with property details including url_pattern
        
    Returns:
        Extracted ID or None if not found
    """
    if not property_details.get("url_pattern"):
        return None
            
    try:
        pattern = property_details["url_pattern"]
        # If pattern uses Wikidata's capture group syntax, extract the ID
        match = re.search(pattern, url)
        if match and match.groups():
            return match.group(1)
    except re.error:
        logger.warning(f"Invalid regex pattern: {pattern}")
    
    return None


def validate_id_format(id_value, format_constraint):
    """
    Validate an ID against a format constraint.
    
    Args:
        id_value: ID value to validate
        format_constraint: Regex pattern for validation
        
    Returns:
        True if valid, False otherwise
    """
    if not format_constraint:
        return True
        
    try:
        pattern = f"^{format_constraint}$"
        return bool(re.match(pattern, id_value))
    except re.error:
        logger.warning(f"Invalid format constraint pattern: {format_constraint}")
        return False


def get_platform_metadata_via_search(domain):
    """
    Search for a platform in Wikidata based on its domain.
    
    Args:
        domain: Domain name (e.g., openreview.net)
        
    Returns:
        Dictionary with platform metadata or None if not found
    """
    # Step 1: Find platform items in Wikidata
    platform_items = find_platform_in_wikidata(domain)
    if not platform_items:
        logger.warning(f"Could not find platform items for domain: {domain}")
        return None
    
    # Step 2: Initialize platform metadata
    platform_data = {
        "domain": domain,
        "wikidata_items": platform_items,
        "identifier_properties": []
    }
    
    # Step 3: Find identifier properties for each platform item
    for item in platform_items:
        item_id = item["id"]
        property_ids = find_identifier_properties(item_id)
        
        if not property_ids:
            continue
            
        # Step 4: Get details for each property
        for prop_id in property_ids:
            # Add delay to avoid overwhelming the API
            time.sleep(0.5)
            
            prop_details = get_property_details(prop_id)
            if not prop_details:
                continue
                
            # Only include identifier properties with formatter URL or URL pattern
            if prop_details.get("formatter_url") or prop_details.get("url_pattern"):
                # Check if this property applies to the platform item we found
                applies_to_item = False
                if prop_details.get("applicable_item") == item_id:
                    applies_to_item = True
                
                # If not explicitly linked, check datatype to filter to external IDs
                if not applies_to_item and prop_details.get("datatype") == "external-id":
                    applies_to_item = True
                
                if applies_to_item:
                    # Convert to simplified format for our use
                    simplified_prop = {
                        "id": prop_details["id"],
                        "label": prop_details["label"],
                        "formatter_url": prop_details.get("formatter_url", ""),
                        "url_pattern": prop_details.get("url_pattern", ""),
                        "format_constraint": prop_details.get("format_constraint", "")
                    }
                    
                    # Check if we already have this property
                    existing_ids = [p["id"] for p in platform_data["identifier_properties"]]
                    if prop_details["id"] not in existing_ids:
                        platform_data["identifier_properties"].append(simplified_prop)
    
    return platform_data


def get_property_by_id(property_id):
    """
    Get property details directly by ID, for use with known platforms.
    
    Args:
        property_id: Wikidata property ID (e.g., P356 for DOI)
        
    Returns:
        Dictionary with property details or None
    """
    prop_details = get_property_details(property_id)
    if not prop_details:
        return None
        
    return {
        "id": prop_details["id"],
        "label": prop_details["label"],
        "formatter_url": prop_details.get("formatter_url", ""),
        "url_pattern": prop_details.get("url_pattern", ""),
        "format_constraint": prop_details.get("format_constraint", "")
    }


# Known property IDs for common platforms
KNOWN_PLATFORMS = {
    "openreview.net": ["P8968", "P8964", "P8965"],
    "arxiv.org": ["P818"],
    "doi.org": ["P356"],
    "orcid.org": ["P496"],
    "semanticscholar.org": ["P4028"],
    "pubmed.ncbi.nlm.nih.gov": ["P698"]
}


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
    
    # Initialize platform data
    platform_data = {
        "domain": domain,
        "wikidata_items": [],
        "identifier_properties": []
    }
    
    # First approach: Use known platform data if available
    if domain in KNOWN_PLATFORMS:
        logger.info(f"Using known property IDs for {domain}")
        platform_found = False
        
        for prop_id in KNOWN_PLATFORMS[domain]:
            prop_details = get_property_by_id(prop_id)
            if prop_details:
                if not platform_found:
                    # If we have at least one property, try to get its applicable item
                    if prop_details.get("applicable_item"):
                        item_id = prop_details["applicable_item"]
                        # Get item details (simplified for this example)
                        platform_data["wikidata_items"].append({
                            "id": item_id,
                            "label": f"Item {item_id}",
                            "description": "",
                            "website": f"https://{domain}"
                        })
                        platform_found = True
                
                platform_data["identifier_properties"].append(prop_details)
    
    # Second approach: Search for platform in Wikidata
    if not platform_data["identifier_properties"]:
        logger.info(f"Searching Wikidata for platform: {domain}")
        search_result = get_platform_metadata_via_search(domain)
        if search_result:
            platform_data = search_result
    
    # If a specific property ID was provided, get its details
    if property_id and property_id not in [p["id"] for p in platform_data["identifier_properties"]]:
        prop_details = get_property_by_id(property_id)
        if prop_details:
            platform_data["identifier_properties"].append(prop_details)
    
    # Extract identifiers from URL
    platform_data["extracted_ids"] = {}
    platform_data["formatted_urls"] = {}
    
    for prop in platform_data["identifier_properties"]:
        extracted_id = extract_id_from_url(url, prop)
        if extracted_id:
            # Validate against format constraint if available
            is_valid = validate_id_format(extracted_id, prop.get("format_constraint"))
            if is_valid:
                platform_data["extracted_ids"][prop["id"]] = {
                    "id": extracted_id,
                    "property": prop
                }
                
                # Generate formatted URL if formatter is available
                if prop.get("formatter_url"):
                    formatted_url = prop["formatter_url"].replace("$1", extracted_id)
                    platform_data["formatted_urls"][prop["id"]] = formatted_url
    
    # If no identifiers were extracted but we have properties with URL patterns,
    # try a different approach: look for common ID patterns in the URL
    if not platform_data["extracted_ids"]:
        for prop in platform_data["identifier_properties"]:
            if prop.get("url_pattern"):
                # Try a more general pattern based on the domain and common ID formats
                if domain == "doi.org":
                    # DOIs often follow pattern: 10.XXXX/YYYY
                    doi_match = re.search(r'(10\.\d+/[^/\s]+)$', url)
                    if doi_match:
                        extracted_id = doi_match.group(1)
                        platform_data["extracted_ids"][prop["id"]] = {
                            "id": extracted_id,
                            "property": prop
                        }
                        if prop.get("formatter_url"):
                            formatted_url = prop["formatter_url"].replace("$1", extracted_id)
                            platform_data["formatted_urls"][prop["id"]] = formatted_url
    
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

#!/usr/bin/env python3
# improved_demo.py - Improved demo for research platform metadata extraction

import json
from loguru import logger
import fire
#from improved_platform_metadata import analyze_research_platform


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
    
    # Print complete metadata
    logger.info("\nComplete metadata (JSON):")
    print(json.dumps(result, indent=2))
    
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
    
    # Print complete metadata
    logger.info("\nComplete metadata (JSON):")
    print(json.dumps(result, indent=2))
    
    return result


def demonstrate_orcid():
    """Demonstrate metadata extraction for ORCID."""
    # Sample URL from ORCID
    url = "https://orcid.org/0000-0002-1825-0097"
    property_id = "P496"  # ORCID ID
    
    logger.info("\n" + "=" * 80)
    logger.info("DEMONSTRATING ORCID METADATA EXTRACTION")
    logger.info("=" * 80)
    
    result = analyze_research_platform(url, property_id)
    
    # Show how to use the extracted ORCID ID
    if result and result["extracted_ids"] and property_id in result["extracted_ids"]:
        orcid_id = result["extracted_ids"][property_id]["id"]
        logger.info(f"\nExtracted ORCID ID: {orcid_id}")
        
        # Show how to use this with ORCID API
        logger.info("\nExample of using this ID with ORCID API:")
        api_url = f"https://pub.orcid.org/v3.0/{orcid_id}"
        logger.info(f"API URL: {api_url}")
    
    # Print complete metadata
    logger.info("\nComplete metadata (JSON):")
    print(json.dumps(result, indent=2))
    
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
    
    # Print complete metadata
    logger.info("\nComplete metadata (JSON):")
    print(json.dumps(result, indent=2))
    
    return result


def main(mode="all", url=None, property_id=None):
    """
    Run demonstration of research platform metadata extraction.
    
    Args:
        mode: One of "all", "openreview", "arxiv", "doi", "orcid", "custom", or "url"
        url: URL to analyze if mode is "url"
        property_id: Optional Wikidata property ID to use for extraction
    """
    if mode == "all":
        demonstrate_openreview()
        demonstrate_arxiv()
        demonstrate_doi()
        demonstrate_orcid()
    elif mode == "openreview":
        demonstrate_openreview()
    elif mode == "arxiv":
        demonstrate_arxiv()
    elif mode == "doi":
        demonstrate_doi()
    elif mode == "orcid":
        demonstrate_orcid()
    elif mode == "custom":
        demonstrate_custom()
    elif mode == "url" and url:
        result = analyze_research_platform(url, property_id)
        print(json.dumps(result, indent=2))
    else:
        logger.error(f"Invalid mode: {mode}")
        logger.info("Available modes: all, openreview, arxiv, doi, orcid, custom, url")


if __name__ == "__main__":
    fire.Fire(main)
