#!/usr/bin/env python3
"""
Google Timeline naar GPX Exporter

Exporteert:
- Routes (<rte>) voor activity segments met start/eindpunt (verplaatsingen)
- Tracks (<trk>) voor timelinePath data (ruwe GPS punten)

Gebruik:
    python timeline_to_gpx.py                    # Standaard: beide formaten
    python timeline_to_gpx.py --format routes    # Alleen routes
    python timeline_to_gpx.py --format tracks    # Alleen tracks
"""

import os
import json
import argparse
import xml.etree.ElementTree as ET
import xml.dom.minidom
from datetime import datetime

# Configuratie
startDate = '2000-01-01'
endDate = '2099-12-31'
verbose = True
groupByMonth = True


def parse_coords(coord_string):
    """Parse coördinaten string naar lat/lon tuple"""
    if not coord_string:
        return None, None
    raw = coord_string.replace("°", "").strip()
    parts = raw.split(", ")
    if len(parts) == 2:
        try:
            return float(parts[0]), float(parts[1])
        except ValueError:
            return None, None
    return None, None


def parse_timestamp(time_str):
    """Parse timestamp en return ISO format"""
    if not time_str:
        return None
    try:
        clean = time_str.replace(".000", "")
        return datetime.fromisoformat(clean.replace('Z', '+00:00'))
    except ValueError:
        return None


def create_gpx_tracks(points, output_file):
    """Maak GPX bestand met tracks (voor ruwe GPS punten)"""
    gpx = ET.Element("gpx", 
                     version="1.1", 
                     creator="Timeline-GPX-Exporter",
                     xmlns="http://www.topografix.com/GPX/1/1")
    
    trk = ET.SubElement(gpx, "trk")
    ET.SubElement(trk, "name").text = f"Track {os.path.basename(output_file)}"
    trkseg = ET.SubElement(trk, "trkseg")
    
    lastDateTime = None
    for point in points:
        dateTime = point["time"]
        # Nieuw segment bij nieuwe dag
        if lastDateTime is not None and lastDateTime[0:10] != dateTime[0:10]:
            trkseg = ET.SubElement(trk, "trkseg")
        
        trkpt = ET.SubElement(trkseg, "trkpt", 
                              lat=str(point["lat"]), 
                              lon=str(point["lon"]))
        ET.SubElement(trkpt, "time").text = dateTime
        lastDateTime = dateTime
    
    write_gpx(gpx, output_file)
    return len(points)


def create_gpx_routes(routes, output_file):
    """Maak GPX bestand met routes (voor activiteiten/verplaatsingen)"""
    gpx = ET.Element("gpx", 
                     version="1.1", 
                     creator="Timeline-GPX-Exporter",
                     xmlns="http://www.topografix.com/GPX/1/1")
    
    for route in routes:
        rte = ET.SubElement(gpx, "rte")
        
        # Route metadata
        name = route.get("name", "Route")
        ET.SubElement(rte, "name").text = name
        
        if route.get("type"):
            ET.SubElement(rte, "type").text = route["type"]
        
        if route.get("description"):
            ET.SubElement(rte, "desc").text = route["description"]
        
        # Route punten
        for i, point in enumerate(route["points"]):
            rtept = ET.SubElement(rte, "rtept",
                                  lat=str(point["lat"]),
                                  lon=str(point["lon"]))
            
            if point.get("time"):
                ET.SubElement(rtept, "time").text = point["time"]
            
            # Optioneel: naam voor start/eindpunt
            if i == 0:
                ET.SubElement(rtept, "name").text = "Start"
            elif i == len(route["points"]) - 1:
                ET.SubElement(rtept, "name").text = "Einde"
    
    write_gpx(gpx, output_file)
    return len(routes)


def write_gpx(gpx_element, output_file):
    """Schrijf GPX element naar bestand met pretty printing"""
    xml_str = xml.dom.minidom.parseString(
        ET.tostring(gpx_element)
    ).toprettyxml(indent='\t')
    
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(xml_str)


def parse_json(input_file):
    """
    Parse Timeline JSON en extraheer zowel tracks als routes
    
    Returns:
        tracks_by_date: dict met ruwe GPS punten per datum
        routes_by_date: dict met activiteit routes per datum
    """
    with open(input_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    tracks_by_date = {}
    routes_by_date = {}
    
    for segment in data.get("semanticSegments", []):
        # Bepaal datum van segment
        start_time = segment.get("startTime")
        if not start_time:
            continue
        
        dt = parse_timestamp(start_time)
        if not dt:
            continue
        
        date = dt.date().isoformat()
        
        # Filter op datum
        if date < startDate or date > endDate:
            continue
        
        # Groepeer per maand indien gewenst
        date_key = date[0:7] if groupByMonth else date
        
        # TRACKS: Verwerk timelinePath (ruwe GPS punten)
        for path_point in segment.get("timelinePath", []):
            try:
                lat, lon = parse_coords(path_point.get("point"))
                if lat is None:
                    continue
                
                time = path_point.get("time", "").replace(".000", "")
                
                if date_key not in tracks_by_date:
                    tracks_by_date[date_key] = []
                
                tracks_by_date[date_key].append({
                    "lat": lat, 
                    "lon": lon, 
                    "time": time
                })
            except (KeyError, ValueError):
                continue
        
        # ROUTES: Verwerk activity segments (verplaatsingen met start/eind)
        activity = segment.get("activity")
        if activity:
            start_lat, start_lon = parse_coords(activity.get("start"))
            end_lat, end_lon = parse_coords(activity.get("end"))
            
            # Alleen routes maken als we start EN eind hebben
            if start_lat is not None and end_lat is not None:
                top_candidate = activity.get("topCandidate", {})
                activity_type = top_candidate.get("type", "UNKNOWN")
                distance = activity.get("distanceMeters")
                
                end_time = segment.get("endTime", "").replace(".000", "")
                start_time_clean = start_time.replace(".000", "")
                
                # Bouw route beschrijving
                desc_parts = []
                if distance:
                    desc_parts.append(f"{distance/1000:.1f} km")
                if activity_type:
                    desc_parts.append(activity_type)
                
                route = {
                    "name": f"{activity_type} {start_time_clean[11:16]}",
                    "type": activity_type,
                    "description": " - ".join(desc_parts) if desc_parts else None,
                    "points": [
                        {"lat": start_lat, "lon": start_lon, "time": start_time_clean},
                        {"lat": end_lat, "lon": end_lon, "time": end_time}
                    ]
                }
                
                # Voeg tussenliggende punten toe als timelinePath beschikbaar is
                timeline_path = segment.get("timelinePath", [])
                if timeline_path:
                    intermediate_points = []
                    for path_point in timeline_path:
                        lat, lon = parse_coords(path_point.get("point"))
                        if lat is not None:
                            time = path_point.get("time", "").replace(".000", "")
                            intermediate_points.append({
                                "lat": lat, 
                                "lon": lon, 
                                "time": time
                            })
                    
                    if intermediate_points:
                        # Vervang route punten met volledige path
                        route["points"] = intermediate_points
                
                if date_key not in routes_by_date:
                    routes_by_date[date_key] = []
                
                routes_by_date[date_key].append(route)
    
    return tracks_by_date, routes_by_date


def main():
    parser = argparse.ArgumentParser(
        description='Exporteer Google Timeline naar GPX formaat',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Voorbeelden:
  %(prog)s                           # Exporteer beide formaten
  %(prog)s --format routes           # Alleen routes (verplaatsingen)
  %(prog)s --format tracks           # Alleen tracks (GPS punten)
  %(prog)s --input mijn_timeline.json --output /pad/naar/output
        """
    )
    parser.add_argument('--input', '-i', default='Timeline.json',
                        help='Input JSON bestand (default: Timeline.json)')
    parser.add_argument('--output', '-o', default='GPX_Output',
                        help='Output directory (default: GPX_Output)')
    parser.add_argument('--format', '-f', choices=['tracks', 'routes', 'both'],
                        default='both',
                        help='Export formaat: tracks, routes, of both (default: both)')
    parser.add_argument('--start', default='2000-01-01',
                        help='Start datum filter (YYYY-MM-DD)')
    parser.add_argument('--end', default='2099-12-31',
                        help='Eind datum filter (YYYY-MM-DD)')
    parser.add_argument('--monthly', action='store_true', default=True,
                        help='Groepeer per maand (default: True)')
    parser.add_argument('--daily', action='store_true',
                        help='Groepeer per dag ipv maand')
    parser.add_argument('--quiet', '-q', action='store_true',
                        help='Onderdruk output berichten')
    
    args = parser.parse_args()
    
    # Configuratie toepassen
    global startDate, endDate, verbose, groupByMonth
    startDate = args.start
    endDate = args.end
    verbose = not args.quiet
    groupByMonth = not args.daily
    
    script_dir = os.getcwd()
    input_file = args.input if os.path.isabs(args.input) else os.path.join(script_dir, args.input)
    output_dir = args.output if os.path.isabs(args.output) else os.path.join(script_dir, args.output)
    
    if not os.path.exists(input_file):
        print(f"Input bestand niet gevonden: {input_file}")
        return 1
    
    os.makedirs(output_dir, exist_ok=True)
    
    if verbose:
        print(f"Verwerken van: {input_file}")
        print(f"Output directory: {output_dir}")
        print(f"Formaat: {args.format}")
        print()
    
    tracks_by_date, routes_by_date = parse_json(input_file)
    
    total_tracks = 0
    total_routes = 0
    
    # Exporteer tracks
    if args.format in ['tracks', 'both']:
        if verbose:
            print("=== TRACKS ===")
        for date, points in sorted(tracks_by_date.items()):
            output_file = os.path.join(output_dir, f"{date}_track.gpx")
            count = create_gpx_tracks(points, output_file)
            total_tracks += count
            if verbose:
                print(f"  {output_file}: {count} punten")
    
    # Exporteer routes
    if args.format in ['routes', 'both']:
        if verbose:
            print("\n=== ROUTES ===")
        for date, routes in sorted(routes_by_date.items()):
            output_file = os.path.join(output_dir, f"{date}_routes.gpx")
            count = create_gpx_routes(routes, output_file)
            total_routes += count
            if verbose:
                print(f"  {output_file}: {count} routes")
    
    if verbose:
        print(f"\n✓ Gereed!")
        if args.format in ['tracks', 'both']:
            print(f"  Totaal track punten: {total_tracks}")
        if args.format in ['routes', 'both']:
            print(f"  Totaal routes: {total_routes}")
    
    return 0


if __name__ == "__main__":
    exit(main())
