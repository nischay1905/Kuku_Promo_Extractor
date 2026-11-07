def optimize_boundaries(candidate, parsed_events):
    """
    Takes a promising candidate and micro-adjusts the start/end points 
    using the legal cut points defined in features.py.
    """
    best_candidate = candidate
    highest_score = candidate['hybrid_quality_score']
    
    # 1. Find adjacent legal camera cuts/dialogue ends within a 5-second radius
    legal_starts = get_adjacent_legal_cuts(candidate.start_event, parsed_events, direction="backward", radius_sec=5)
    legal_ends = get_adjacent_legal_cuts(candidate.end_event, parsed_events, direction="forward", radius_sec=5)
    
    # 2. Grid search the micro-adjustments
    for start in legal_starts:
        for end in legal_ends:
            duration = end.timestamp - start.timestamp
            
            # Hard constraint check
            if not (20 <= duration <= 60):
                continue
                
            # Create counterfactual window
            alt_candidate = build_candidate(start, end)
            
            # Re-evaluate with the Independent Judges
            alt_score = evaluate_candidate(alt_candidate)
            
            # If expanding the clip added a better cliffhanger without adding context debt, keep it
            if alt_score > highest_score:
                highest_score = alt_score
                best_candidate = alt_candidate
                
    return best_candidate