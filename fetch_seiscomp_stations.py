#!/usr/bin/env python3
"""
fetch_seiscomp_stations.py

Connects to a SeisComP server (e.g. sysop@10.27.192.214), downloads station inventory
XML files (such as Dataless.OK.*.seed.xml) from /home/sysop/seiscomp3/etc/inventory/,
parses station metadata (coordinates, elevation, channels, active dates, heliplot URLs),
and exports the dataset to JSON, CSV, and a new interactive HTML dashboard.
"""

import sys
import os
import re
import csv
import json
import fnmatch
import argparse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

# Default Remote Server Configuration
DEFAULT_HOST = "10.27.192.214"
DEFAULT_USER = "sysop"
DEFAULT_PASS = "sysop"
DEFAULT_PORT = 22
DEFAULT_REMOTE_DIR = "/home/sysop/seiscomp3/etc/inventory"
DEFAULT_LOCAL_DIR = "./seiscomp3_inventory"
DEFAULT_PATTERN = "Dataless.*.seed.xml"
DEFAULT_HELIPLOT_BASE = "http://wichita.ogs.ou.edu/eq/heliplot"


def local_strip_tag(tag):
    """Strip XML namespace from tag if present."""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def fetch_files_via_scp(host, user, password, port, remote_dir, local_dir, pattern="*.xml", quiet=False):
    """
    Downloads inventory XML files using SCP with pexpect to handle authentication.
    """
    import pexpect

    os.makedirs(local_dir, exist_ok=True)
    pattern_escaped = pattern if pattern else "*.xml"
    scp_cmd = f"scp -o StrictHostKeyChecking=no -P {port} {user}@{host}:{remote_dir}/{pattern_escaped} {local_dir}/"

    if not quiet:
        print(f"[*] Downloading XML inventory via SCP from {user}@{host}:{remote_dir}/{pattern_escaped}...")

    child = pexpect.spawn(scp_cmd, timeout=90)
    idx = child.expect(["password:", pexpect.EOF, pexpect.TIMEOUT])
    if idx == 0:
        child.sendline(password)
        child.expect(pexpect.EOF, timeout=120)
    elif idx == 2:
        raise TimeoutError(f"Connection timeout to {host}:{port}")

    files = [
        os.path.join(local_dir, f)
        for f in os.listdir(local_dir)
        if fnmatch.fnmatch(f, pattern_escaped)
    ]
    if not quiet:
        print(f"[+] Downloaded {len(files)} XML files to '{local_dir}/'")
    return files


def download_inventory(host, user, password, port, remote_dir, local_dir, pattern="*.xml", quiet=False):
    """
    Downloads inventory files from remote server.
    """
    return fetch_files_via_scp(host, user, password, port, remote_dir, local_dir, pattern, quiet)


def parse_station_element(sta_elem, net_code, net_desc, source_file, heliplot_base):
    """
    Parses a single <station> XML element and extracts all attributes.
    """
    code = sta_elem.attrib.get("code") or sta_elem.attrib.get("name") or "UNKNOWN"
    
    lat = None
    lon = None
    elev = None
    description = ""
    place = ""
    country = ""
    affiliation = ""
    start_time = None
    end_time = None
    streams = set()

    for child in sta_elem:
        tag = local_strip_tag(child.tag)
        text = (child.text or "").strip()
        
        if tag == "latitude" and text:
            try:
                lat = float(text)
            except ValueError:
                pass
        elif tag == "longitude" and text:
            try:
                lon = float(text)
            except ValueError:
                pass
        elif tag == "elevation" and text:
            try:
                elev = float(text)
            except ValueError:
                pass
        elif tag == "description":
            description = text
        elif tag == "place":
            place = text
        elif tag == "country":
            country = text
        elif tag == "affiliation":
            affiliation = text
        elif tag == "start":
            start_time = text
        elif tag == "end":
            end_time = text
        elif tag == "sensorLocation":
            for sl_child in child:
                sl_tag = local_strip_tag(sl_child.tag)
                if sl_tag == "stream":
                    st_code = sl_child.attrib.get("code")
                    if st_code:
                        streams.add(st_code)
                    for stream_sub in sl_child:
                        if local_strip_tag(stream_sub.tag) == "code" and stream_sub.text:
                            streams.add(stream_sub.text.strip())

    if lat is None or lon is None:
        return None

    # Determine active status
    is_active = True
    if end_time:
        try:
            end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
            if end_dt < datetime.now(timezone.utc):
                is_active = False
        except Exception:
            pass

    heliplot_url = f"{heliplot_base.rstrip('/')}/{code}.png"

    return {
        "Station": code,
        "Network": net_code,
        "NetworkDescription": net_desc,
        "latitude": round(lat, 6),
        "longitude": round(lon, 6),
        "elevation": elev if elev is not None else 0.0,
        "description": description or f"{code}, {net_code}",
        "place": place or code,
        "country": country or "USA",
        "affiliation": affiliation or "Oklahoma Geological Survey",
        "start": start_time or "",
        "end": end_time or "",
        "is_active": is_active,
        "channels": sorted(list(streams)),
        "html": heliplot_url,
        "source_xml": os.path.basename(source_file),
    }


def parse_inventory_xml(xml_path, heliplot_base=DEFAULT_HELIPLOT_BASE):
    """
    Parses a SeisComP inventory XML file and extracts all contained stations.
    """
    stations = []
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
    except Exception as err:
        print(f"[-] Warning: Failed to parse XML '{xml_path}': {err}")
        return []

    # Iterate through network elements
    for net_elem in root.iter():
        if local_strip_tag(net_elem.tag) == "network":
            net_code = net_elem.attrib.get("code", "OK")
            net_desc = ""
            for child in net_elem:
                if local_strip_tag(child.tag) == "description" and child.text:
                    net_desc = child.text.strip()
                    break

            for sta_elem in net_elem:
                if local_strip_tag(sta_elem.tag) == "station":
                    sta_info = parse_station_element(
                        sta_elem, net_code, net_desc, xml_path, heliplot_base
                    )
                    if sta_info:
                        stations.append(sta_info)

    return stations


def parse_all_inventory_files(xml_files, heliplot_base=DEFAULT_HELIPLOT_BASE, quiet=False):
    """
    Parses a list of XML files, deduplicating stations (preferring OK network and active records).
    """
    station_map = {}
    total_parsed = 0

    for xml_file in xml_files:
        st_list = parse_inventory_xml(xml_file, heliplot_base)
        total_parsed += len(st_list)
        for sta in st_list:
            key = f"{sta['Network']}.{sta['Station']}"
            if key not in station_map:
                station_map[key] = sta
            else:
                existing = station_map[key]
                existing_channels = set(existing.get("channels", []))
                new_channels = set(sta.get("channels", []))
                existing["channels"] = sorted(list(existing_channels.union(new_channels)))
                if sta["is_active"] and not existing["is_active"]:
                    station_map[key] = sta

    sorted_stations = sorted(list(station_map.values()), key=lambda x: (x["Network"], x["Station"]))
    if not quiet:
        print(f"[+] Extracted {len(sorted_stations)} unique stations from {len(xml_files)} XML files ({total_parsed} total station records parsed).")
    return sorted_stations


def export_stations_json(stations, json_path, quiet=False):
    """Exports stations list to JSON."""
    with open(json_path, "w", encoding="utf-8") as jf:
        json.dump(stations, jf, indent=2)
    if not quiet:
        print(f"[+] Saved JSON catalog: {json_path} ({len(stations)} stations)")


def export_stations_csv(stations, csv_path, quiet=False):
    """Exports stations list to CSV."""
    fields = [
        "Network",
        "Station",
        "latitude",
        "longitude",
        "elevation",
        "place",
        "description",
        "affiliation",
        "start",
        "end",
        "is_active",
        "channels",
        "html",
        "source_xml",
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as cf:
        writer = csv.DictWriter(cf, fieldnames=fields)
        writer.writeheader()
        for s in stations:
            row = dict(s)
            row["channels"] = ",".join(row.get("channels", []))
            writer.writerow({k: row.get(k, "") for k in fields})
    if not quiet:
        print(f"[+] Saved CSV catalog: {csv_path}")


def generate_html_with_stations(template_html, output_html, stations, quiet=False):
    """
    Generates a new HTML dashboard by embedding the parsed STATIC_STATIONS
    and updating the station rendering layer.
    """
    if not os.path.exists(template_html):
        raise FileNotFoundError(f"Template HTML not found: {template_html}")

    with open(template_html, "r", encoding="utf-8") as tf:
        html_content = tf.read()

    # Format STATIC_STATIONS JSON
    clean_stations = []
    for s in stations:
        clean_stations.append({
            "Station": s["Station"],
            "Network": s["Network"],
            "latitude": s["latitude"],
            "longitude": s["longitude"],
            "elevation": s["elevation"],
            "description": s["description"],
            "place": s["place"],
            "channels": s["channels"],
            "is_active": s["is_active"],
            "html": s["html"],
        })

    stations_js = "const STATIC_STATIONS = " + json.dumps(clean_stations, indent=2) + ";"

    # Regex replace STATIC_STATIONS declaration
    pattern = re.compile(r"const\s+STATIC_STATIONS\s*=\s*\[.*?\]\s*;", re.DOTALL)
    if pattern.search(html_content):
        updated_html = pattern.sub(stations_js, html_content)
    else:
        updated_html = html_content.replace("<script>", f"<script>\n{stations_js}\n", 1)

    # Replace plotStationsFromStatic implementation with rich popup
    old_plot_stations = re.compile(
        r"function\s+plotStationsFromStatic\s*\(\)\s*\{.*?\n\s*layerGroups\.stations\.bringToBack\(\);\s*\}",
        re.DOTALL,
    )

    new_plot_stations = """function plotStationsFromStatic() {
          if (STATIC_STATIONS && Array.isArray(STATIC_STATIONS)) {
            layerGroups.stations.clearLayers();
            STATIC_STATIONS.forEach((sta) => {
              const icon = L.divIcon({
                className: "station-icon",
                html: '<svg height="15" width="15"><polygon points="7.5,0 15,15 0,15" style="fill:black;stroke:white;stroke-width:1" /></svg>',
                iconSize: [15, 15],
                iconAnchor: [7.5, 7.5],
              });
              const statusBadge = sta.is_active 
                ? "<span style='display:inline-block;padding:1px 6px;border-radius:10px;font-size:10px;font-weight:700;background:#f0fdf4;color:#15803d;'>ACTIVE</span>"
                : "<span style='display:inline-block;padding:1px 6px;border-radius:10px;font-size:10px;font-weight:700;background:#fef2f2;color:#991b1b;'>DECOMMISSIONED</span>";

              const chText = (sta.channels && sta.channels.length > 0) ? sta.channels.join(", ") : "N/A";
              const netLabel = sta.Network ? sta.Network + "." : "";
              const popupContent = `
                <div style="font-family:Montserrat,helvetica,arial,sans-serif; font-size:12px; line-height:1.5; min-width:180px; padding:2px;">
                  <div style="font-weight:700; font-size:13px; color:#1e293b; margin-bottom:4px;">
                    ${netLabel}${sta.Station} ${statusBadge}
                  </div>
                  <div style="font-size:11px; color:#475569; margin-bottom:4px;">${sta.description || sta.place || "Seismic Station"}</div>
                  <div style="font-size:11px; color:#64748b;"><strong>Coordinates:</strong> ${parseFloat(sta.latitude).toFixed(4)}°, ${parseFloat(sta.longitude).toFixed(4)}°</div>
                  <div style="font-size:11px; color:#64748b;"><strong>Elevation:</strong> ${sta.elevation !== null && sta.elevation !== undefined ? sta.elevation + " m" : "N/A"}</div>
                  <div style="font-size:11px; color:#64748b;"><strong>Channels:</strong> ${chText}</div>
                  <div style="margin-top:6px; border-top:1px solid #e2e8f0; padding-top:4px;">
                    <a href="${sta.html}" target="_blank" style="display:inline-block; color:#2563eb; font-weight:700; text-decoration:none; font-size:11px; background:#eff6ff; padding:3px 8px; border-radius:4px;">📊 View 24h Heliplot</a>
                  </div>
                </div>
              `;
              L.marker([sta.latitude, sta.longitude], { icon })
                .addTo(layerGroups.stations)
                .bindPopup(popupContent);
            });
          }
          layerGroups.stations.bringToBack();
        }"""

    if old_plot_stations.search(updated_html):
        updated_html = old_plot_stations.sub(new_plot_stations, updated_html)

    # In loadStations, use plotStationsFromStatic directly for reliable SeisComP stations
    updated_html = updated_html.replace(
        "loadStations();",
        "plotStationsFromStatic(); // Prioritize authentic SeisComP station inventory\n        // loadStations();",
    )

    # Update page title
    updated_html = updated_html.replace(
        "<title>OGS Interactive Earthquake Map (Self-Contained)</title>",
        "<title>OGS Interactive Earthquake & SeisComP Station Map</title>"
    )

    with open(output_html, "w", encoding="utf-8") as of:
        of.write(updated_html)

    if not quiet:
        print(f"[+] Generated new HTML dashboard: {output_html} with {len(clean_stations)} SeisComP stations!")


def main():
    parser = argparse.ArgumentParser(
        description="Fetch, parse, and export SeisComP station inventory XMLs and update HTML dashboards."
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"SeisComP server IP/host (default: {DEFAULT_HOST})")
    parser.add_argument("--user", default=DEFAULT_USER, help=f"SSH username (default: {DEFAULT_USER})")
    parser.add_argument("--password", default=DEFAULT_PASS, help=f"SSH password (default: {DEFAULT_PASS})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"SSH port (default: {DEFAULT_PORT})")
    parser.add_argument("--remote-dir", default=DEFAULT_REMOTE_DIR, help=f"Remote inventory folder (default: {DEFAULT_REMOTE_DIR})")
    parser.add_argument("--local-dir", default=DEFAULT_LOCAL_DIR, help=f"Local cache directory for XMLs (default: {DEFAULT_LOCAL_DIR})")
    parser.add_argument("--pattern", default=DEFAULT_PATTERN, help=f"File pattern to match (default: '{DEFAULT_PATTERN}', use '*.xml' for all)")
    parser.add_argument("--all-xml", action="store_true", help="Download all XML files (*.xml) rather than just Dataless.*.seed.xml")
    parser.add_argument("--no-download", action="store_true", help="Skip remote download and parse existing local XML files only")
    parser.add_argument("--active-only", action="store_true", help="Include only active stations (exclude decommissioned)")
    parser.add_argument("--heliplot-base", default=DEFAULT_HELIPLOT_BASE, help="Base URL for station heliplots")
    parser.add_argument("--output-json", default="seiscomp_stations.json", help="Path to output JSON file")
    parser.add_argument("--output-csv", default="seiscomp_stations.csv", help="Path to output CSV file")
    parser.add_argument("--template-html", default="OGS_Moni_Dev_USGS-hotpatch-autoload.html", help="Template HTML to inject stations into")
    parser.add_argument("--output-html", default="OGS_Moni_Dev_SeisComP_Stations.html", help="Output HTML filename")
    parser.add_argument("--quiet", "-q", action="store_true", help="Quiet mode (suppress verbose logs)")

    args = parser.parse_args()

    match_pattern = "*.xml" if args.all_xml else args.pattern

    # Step 1: Download or locate XML files
    if not args.no_download:
        if not args.quiet:
            print(f"============================================================")
            print(f"  Fetching SeisComP Station Inventory from {args.user}@{args.host}")
            print(f"  Remote Directory: {args.remote_dir}")
            print(f"  Pattern: {match_pattern}")
            print(f"============================================================")
        
        xml_files = download_inventory(
            host=args.host,
            user=args.user,
            password=args.password,
            port=args.port,
            remote_dir=args.remote_dir,
            local_dir=args.local_dir,
            pattern=match_pattern,
            quiet=args.quiet,
        )
    else:
        if not args.quiet:
            print(f"[*] Skipping remote download. Scanning local '{args.local_dir}/'...")
        xml_files = []
        if os.path.exists(args.local_dir):
            for f in os.listdir(args.local_dir):
                if fnmatch.fnmatch(f, match_pattern):
                    xml_files.append(os.path.join(args.local_dir, f))

    if not xml_files:
        print("[-] No XML files found to parse. Exiting.")
        sys.exit(1)

    # Step 2: Parse station XMLs
    stations = parse_all_inventory_files(xml_files, heliplot_base=args.heliplot_base, quiet=args.quiet)

    if args.active_only:
        stations = [s for s in stations if s["is_active"]]
        if not args.quiet:
            print(f"[*] Filtered to {len(stations)} active stations.")

    # Step 3: Export JSON & CSV
    export_stations_json(stations, args.output_json, quiet=args.quiet)
    export_stations_csv(stations, args.output_csv, quiet=args.quiet)

    # Step 4: Generate HTML dashboard
    if os.path.exists(args.template_html):
        generate_html_with_stations(args.template_html, args.output_html, stations, quiet=args.quiet)
    else:
        print(f"[-] Warning: Template HTML '{args.template_html}' not found. HTML generation skipped.")

    if not args.quiet:
        print(f"\n[✓] All tasks completed successfully!")


if __name__ == "__main__":
    main()
