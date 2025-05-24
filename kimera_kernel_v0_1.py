import networkx as nx
from sentence_transformers import SentenceTransformer
import spacy
import numpy as np
import uuid

# Installation instructions:
# pip install networkx sentence_transformers spacy numpy
# python -m spacy download en_core_web_sm

class KimeraKernel:
    """
    The core of the Kimera system, responsible for managing Geoids (Geometric Object IDs)
    and their relationships within a knowledge graph.
    """
    def __init__(self):
        """
        Initializes the KimeraKernel with an empty NetworkX graph to store Geoids
        and loads the sentence transformer model.
        """
        self.graph = nx.Graph()
        self.model = SentenceTransformer('all-MiniLM-L6-v2')
        try:
            self.nlp = spacy.load('en_core_web_sm')
        except OSError:
            print("Downloading en_core_web_sm for spaCy...")
            spacy.cli.download('en_core_web_sm')
            self.nlp = spacy.load('en_core_web_sm')


    def add_geoid(self, content: str, dimensions: dict = None, source: str = None, geoid_id: str = None) -> str:
        """
        Adds a new Geoid to the kernel's graph.

        Args:
            content: The textual content of the Geoid.
            dimensions: Optional dictionary of pre-defined dimensions for the Geoid.
            source: Optional string indicating the origin of the Geoid's content.
            geoid_id: Optional custom ID for the Geoid. If None, a unique ID is generated.

        Returns:
            The ID of the added Geoid.
        """
        if geoid_id is None:
            geoid_id = str(uuid.uuid4())

        core_embedding = self.model.encode(content)
        
        # Initialize dimensions if not provided, ensuring 'structural_pattern_abstracted' is present
        if dimensions is None:
            dimensions = {}
        if 'structural_pattern_abstracted' not in dimensions:
            dimensions['structural_pattern_abstracted'] = None

        self.graph.add_node(
            geoid_id,
            content=content,
            core_embedding=core_embedding,
            dimensions=dimensions, # Store the whole dict
            source=source,
            activation_status=0.0,
            contradiction_flag=False
        )
        return geoid_id

    def get_geoid(self, geoid_id: str) -> dict:
        """
        Retrieves the data associated with a specific Geoid.

        Args:
            geoid_id: The ID of the Geoid to retrieve.

        Returns:
            A dictionary containing the Geoid's attributes.
            Returns an empty dictionary if the Geoid is not found.
        """
        if self.graph.has_node(geoid_id):
            return self.graph.nodes[geoid_id]
        return {}

    def update_geoid_dimension(self, geoid_id: str, dim_name: str, dim_value: any):
        """
        Updates a specific key within the 'dimensions' dictionary of a Geoid.

        Args:
            geoid_id: The ID of the Geoid to update.
            dim_name: The name of the dimension (key) to update within the 'dimensions' dictionary.
            dim_value: The new value for the dimension.
        
        Raises:
            KeyError: If the geoid_id is not found in the graph.
        """
        if not self.graph.has_node(geoid_id):
            raise KeyError(f"Geoid with ID '{geoid_id}' not found.")

        # Ensure the 'dimensions' attribute exists and is a dictionary
        if 'dimensions' not in self.graph.nodes[geoid_id] or not isinstance(self.graph.nodes[geoid_id]['dimensions'], dict):
            self.graph.nodes[geoid_id]['dimensions'] = {}
            
        self.graph.nodes[geoid_id]['dimensions'][dim_name] = dim_value


class PatternAbstractor:
    """
    Responsible for extracting structural patterns from Geoid content.
    """
    def abstract_pattern_basic(self, kernel: KimeraKernel, geoid_id: str) -> str:
        """
        Extracts keywords (top 3-5 nouns/verbs) from a Geoid's content using spaCy.
        Updates the Geoid's 'structural_pattern_abstracted' dimension.

        Args:
            kernel: The KimeraKernel instance.
            geoid_id: The ID of the Geoid to process.

        Returns:
            A string representing the abstracted pattern (keywords joined by underscore).
            Returns an empty string if the Geoid is not found or content is empty.
        """
        geoid_data = kernel.get_geoid(geoid_id)
        if not geoid_data or not geoid_data.get('content'):
            return ""

        content = geoid_data['content']
        doc = kernel.nlp(content) # Use kernel's nlp instance

        keywords = [
            token.lemma_.lower() for token in doc 
            if token.pos_ in ('NOUN', 'VERB') and not token.is_stop
        ]
        
        # Get top 3-5 keywords (can be refined further based on frequency or other metrics)
        # For simplicity, taking the first 5 unique keywords.
        unique_keywords = []
        for kw in keywords:
            if kw not in unique_keywords:
                unique_keywords.append(kw)
        
        top_keywords = unique_keywords[:5]

        kernel.update_geoid_dimension(geoid_id, 'structural_pattern_abstracted', top_keywords)
        
        return "_".join(top_keywords)


class ResonanceDetector:
    """
    Detects resonance between pairs of Geoids based on semantic and pattern similarity.
    """
    def _cosine_similarity(self, vec1, vec2):
        """Helper function to compute cosine similarity."""
        if vec1 is None or vec2 is None:
            return 0.0
        vec1 = np.asarray(vec1)
        vec2 = np.asarray(vec2)
        if vec1.shape != vec2.shape: # Should not happen with sentence transformers if used correctly
             print(f"Warning: Embeddings have different shapes: {vec1.shape} vs {vec2.shape}")
             return 0.0
        if np.linalg.norm(vec1) == 0 or np.linalg.norm(vec2) == 0:
            return 0.0
        return np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2))

    def _jaccard_similarity(self, list1, list2):
        """Helper function to compute Jaccard similarity for lists of keywords."""
        if not list1 or not list2: # Handle cases where patterns might be empty or None
            return 0.0
        set1 = set(list1)
        set2 = set(list2)
        intersection = len(set1.intersection(set2))
        union = len(set1.union(set2))
        return intersection / union if union != 0 else 0.0

    def detect_resonance_basic(self, kernel: KimeraKernel, geoid_A_id: str, geoid_B_id: str, 
                               semantic_threshold: float = 0.7, pattern_threshold: float = 0.3) -> dict:
        """
        Detects resonance between two Geoids based on semantic and pattern similarity.

        Args:
            kernel: The KimeraKernel instance.
            geoid_A_id: ID of the first Geoid.
            geoid_B_id: ID of the second Geoid.
            semantic_threshold: Minimum cosine similarity for semantic resonance.
            pattern_threshold: Minimum Jaccard similarity for pattern resonance.

        Returns:
            A dictionary containing:
                'resonant': bool,
                'semantic_score': float,
                'pattern_score': float
        """
        geoid_A_data = kernel.get_geoid(geoid_A_id)
        geoid_B_data = kernel.get_geoid(geoid_B_id)

        if not geoid_A_data or not geoid_B_data:
            return {'resonant': False, 'semantic_score': 0.0, 'pattern_score': 0.0, 'error': 'One or both Geoids not found.'}

        # Semantic Similarity
        embedding_A = geoid_A_data.get('core_embedding')
        embedding_B = geoid_B_data.get('core_embedding')
        semantic_similarity = self._cosine_similarity(embedding_A, embedding_B)

        # Pattern Similarity
        pattern_A = geoid_A_data.get('dimensions', {}).get('structural_pattern_abstracted')
        pattern_B = geoid_B_data.get('dimensions', {}).get('structural_pattern_abstracted')
        
        if pattern_A is None or pattern_B is None:
            # This can happen if abstract_pattern_basic was not run on one or both geoids
            print(f"Warning: Pattern not abstracted for Geoid {geoid_A_id if pattern_A is None else ''} {geoid_B_id if pattern_B is None and pattern_A is not None else ''}")
            pattern_similarity = 0.0 
        else:
            pattern_similarity = self._jaccard_similarity(pattern_A, pattern_B)
            
        is_resonant = (semantic_similarity >= semantic_threshold) and \
                      (pattern_similarity >= pattern_threshold)

        if is_resonant:
            kernel.graph.add_edge(
                geoid_A_id, 
                geoid_B_id, 
                type='resonance', # Added type attribute
                semantic_similarity_score=semantic_similarity,
                pattern_similarity_score=pattern_similarity
            )
            print(f"Resonance detected and edge added between {geoid_A_id} and {geoid_B_id}.")


        return {
            'resonant': is_resonant,
            'semantic_score': float(semantic_similarity), # Ensure float for JSON compatibility if needed
            'pattern_score': float(pattern_similarity)   # Ensure float
        }


class InterpretationEngine:
    """
    Placeholder for interpreting the meaning of resonance between Geoids.
    """
    def interpret_resonance_placeholder(self, kernel: KimeraKernel, geoid_A_id: str, geoid_B_id: str, 
                                        shared_pattern: str = None) -> str:
        """
        Generates a placeholder interpretation for resonance.

        Args:
            kernel: The KimeraKernel instance.
            geoid_A_id: ID of the first Geoid.
            geoid_B_id: ID of the second Geoid.
            shared_pattern: Optional string representing the shared pattern (e.g., from abstractor).

        Returns:
            A string with the placeholder interpretation.
        """
        geoid_A_data = kernel.get_geoid(geoid_A_id)
        geoid_B_data = kernel.get_geoid(geoid_B_id)

        if not geoid_A_data or not geoid_B_data:
            return "Error: One or both Geoids not found for interpretation."

        content_A = geoid_A_data.get('content', '[Content A not found]')
        content_B = geoid_B_data.get('content', '[Content B not found]')
        
        pattern_A_list = geoid_A_data.get('dimensions', {}).get('structural_pattern_abstracted', [])
        pattern_B_list = geoid_B_data.get('dimensions', {}).get('structural_pattern_abstracted', [])
        
        # Determine a more relevant shared_pattern if not provided
        if shared_pattern is None and pattern_A_list and pattern_B_list:
            shared_keywords = set(pattern_A_list).intersection(set(pattern_B_list))
            if shared_keywords:
                shared_pattern = "_".join(sorted(list(shared_keywords))) # Sort for consistency
            else:
                shared_pattern = "[No obvious shared keywords]"


        interpretation = (
            f"--- Interpretation Placeholder ---\n"
            f"Resonance detected between:\n"
            f"  Geoid A ({geoid_A_id}): '{content_A}' (Pattern: {pattern_A_list})\n"
            f"  Geoid B ({geoid_B_id}): '{content_B}' (Pattern: {pattern_B_list})\n"
            f"Shared Pattern Context: {shared_pattern if shared_pattern else '[Pattern not specified/found]'}\n"
            f"Further analysis is needed to generate a detailed interpretation for this resonance.\n"
            f"--- End Interpretation ---"
        )
        return interpretation


def run_swm_cycle_on_pair(kernel: KimeraKernel, abstractor: PatternAbstractor, 
                          detector: ResonanceDetector, interpreter: InterpretationEngine, 
                          geoid_A_id: str, geoid_B_id: str):
    """
    Runs a single Sense-Making & Weaving (SWM) cycle on a pair of Geoids.

    Args:
        kernel: The KimeraKernel instance.
        abstractor: The PatternAbstractor instance.
        detector: The ResonanceDetector instance.
        interpreter: The InterpretationEngine instance.
        geoid_A_id: ID of the first Geoid.
        geoid_B_id: ID of the second Geoid.
    """
    print(f"\n--- Running SWM Cycle for Geoids: {geoid_A_id} and {geoid_B_id} ---")

    # 1. Abstract patterns
    print(f"\nStep 1: Abstracting patterns...")
    pattern_A_str = abstractor.abstract_pattern_basic(kernel, geoid_A_id)
    pattern_B_str = abstractor.abstract_pattern_basic(kernel, geoid_B_id)
    print(f"  Pattern for {geoid_A_id}: {pattern_A_str} (Raw: {kernel.get_geoid(geoid_A_id).get('dimensions', {}).get('structural_pattern_abstracted')})")
    print(f"  Pattern for {geoid_B_id}: {pattern_B_str} (Raw: {kernel.get_geoid(geoid_B_id).get('dimensions', {}).get('structural_pattern_abstracted')})")

    # 2. Detect resonance
    print(f"\nStep 2: Detecting resonance...")
    resonance_results = detector.detect_resonance_basic(kernel, geoid_A_id, geoid_B_id)
    print(f"  Resonance detected: {resonance_results['resonant']}")
    print(f"  Semantic Score: {resonance_results['semantic_score']:.4f}")
    print(f"  Pattern Score: {resonance_results['pattern_score']:.4f}")
    if 'error' in resonance_results:
        print(f"  Error: {resonance_results['error']}")
        return # Stop cycle if error in detection

    # 3. Interpret resonance (if resonant)
    if resonance_results['resonant']:
        print(f"\nStep 3: Interpreting resonance...")
        # We can pass the intersection of patterns as a hint for shared_pattern
        pattern_A_list = kernel.get_geoid(geoid_A_id).get('dimensions', {}).get('structural_pattern_abstracted', [])
        pattern_B_list = kernel.get_geoid(geoid_B_id).get('dimensions', {}).get('structural_pattern_abstracted', [])
        shared_keywords = list(set(pattern_A_list).intersection(set(pattern_B_list)))
        shared_pattern_str = "_".join(sorted(shared_keywords)) if shared_keywords else None

        interpretation_text = interpreter.interpret_resonance_placeholder(kernel, geoid_A_id, geoid_B_id, shared_pattern=shared_pattern_str)
        print(interpretation_text)
    
    print(f"--- End SWM Cycle for {geoid_A_id} and {geoid_B_id} ---")


# Main section for demonstration
if __name__ == "__main__":
    print("Initializing Kimera Kernel v0.1...")
    kernel = KimeraKernel()
    abstractor = PatternAbstractor()
    detector = ResonanceDetector()
    interpreter = InterpretationEngine()

    print("\n--- Adding Sample Geoids ---")
    sample_data = [
        {"id": "concept_apple_fruit", "content": "Apples are round fruits that grow on trees and are typically red, green, or yellow.", "source": "common knowledge"},
        {"id": "concept_apple_company", "content": "Apple Inc. is a technology company that designs and sells consumer electronics, software, and online services.", "source": "wikipedia"},
        {"id": "concept_tree_plant", "content": "A tree is a tall plant with a trunk and branches made of wood. Trees produce oxygen.", "source": "botany basics"},
        {"id": "concept_banana_fruit", "content": "Bananas are long, curved fruits that grow in clusters and are yellow when ripe.", "source": "common knowledge"},
        {"id": "concept_data_analysis", "content": "Data analysis involves inspecting, cleansing, transforming, and modeling data to discover useful information.", "source": "analytics definition"}
    ]

    geoid_ids = []
    for item in sample_data:
        gid = kernel.add_geoid(content=item["content"], source=item["source"], geoid_id=item["id"])
        geoid_ids.append(gid)
        print(f"Added Geoid: ID='{gid}', Content='{item['content'][:50]}...'")

    print("\n--- Retrieving a Sample Geoid ---")
    sample_gid_to_get = geoid_ids[0]
    retrieved_geoid = kernel.get_geoid(sample_gid_to_get)
    if retrieved_geoid:
        print(f"Retrieved Geoid '{sample_gid_to_get}':")
        print(f"  Content: {retrieved_geoid['content'][:60]}...")
        print(f"  Source: {retrieved_geoid['source']}")
        print(f"  Activation: {retrieved_geoid['activation_status']}")
        # print(f"  Embedding (first 5 dims): {retrieved_geoid['core_embedding'][:5]}") # Potentially long
    else:
        print(f"Could not retrieve Geoid '{sample_gid_to_get}'.")

    print("\n--- Updating a Geoid Dimension ---")
    gid_to_update = geoid_ids[1] # Apple Inc.
    print(f"Before update, dimensions for '{gid_to_update}': {kernel.get_geoid(gid_to_update).get('dimensions')}")
    kernel.update_geoid_dimension(gid_to_update, 'market_cap_approx_usd', '3T')
    kernel.update_geoid_dimension(gid_to_update, 'structural_pattern_abstracted', ['company', 'technology', 'electronics']) # Manual override for demo
    print(f"After update, dimensions for '{gid_to_update}': {kernel.get_geoid(gid_to_update).get('dimensions')}")


    print("\n--- Abstracting Patterns for all Sample Geoids ---")
    for gid in geoid_ids:
        pattern_str = abstractor.abstract_pattern_basic(kernel, gid)
        retrieved_pattern = kernel.get_geoid(gid).get('dimensions', {}).get('structural_pattern_abstracted')
        print(f"  Geoid '{gid}': Abstracted pattern string = '{pattern_str}', Stored keywords = {retrieved_pattern}")


    print("\n--- Demonstrating Resonance Detection (Pairwise) ---")
    # Example 1: apple (fruit) vs banana (fruit) - expected high semantic, moderate pattern
    gid_apple_fruit = "concept_apple_fruit"
    gid_banana_fruit = "concept_banana_fruit"
    print(f"\nComparing '{gid_apple_fruit}' and '{gid_banana_fruit}':")
    resonance_fruit_pair = detector.detect_resonance_basic(kernel, gid_apple_fruit, gid_banana_fruit, semantic_threshold=0.5, pattern_threshold=0.1)
    print(f"  Result: {resonance_fruit_pair}")
    if resonance_fruit_pair.get('resonant'):
         print(kernel.graph.edges[gid_apple_fruit, gid_banana_fruit])


    # Example 2: apple (fruit) vs apple (company) - expected lower semantic, potentially low pattern
    gid_apple_company = "concept_apple_company"
    # Ensure pattern is abstracted for apple_company if not done above or overridden
    if kernel.get_geoid(gid_apple_company).get('dimensions',{}).get('structural_pattern_abstracted') is None:
        print(f"Abstracting pattern for {gid_apple_company} before resonance detection...")
        abstractor.abstract_pattern_basic(kernel, gid_apple_company)
        print(f"  Pattern for {gid_apple_company}: {kernel.get_geoid(gid_apple_company).get('dimensions',{}).get('structural_pattern_abstracted')}")


    print(f"\nComparing '{gid_apple_fruit}' and '{gid_apple_company}':")
    resonance_apple_vs_apple = detector.detect_resonance_basic(kernel, gid_apple_fruit, gid_apple_company, semantic_threshold=0.3, pattern_threshold=0.05) # Lower thresholds for demo
    print(f"  Result: {resonance_apple_vs_apple}")
    if resonance_apple_vs_apple.get('resonant'):
         print(kernel.graph.edges[gid_apple_fruit, gid_apple_company])


    # Example 3: apple (fruit) vs tree (plant) - expected moderate semantic, some pattern overlap
    gid_tree_plant = "concept_tree_plant"
    print(f"\nComparing '{gid_apple_fruit}' and '{gid_tree_plant}':")
    resonance_apple_tree = detector.detect_resonance_basic(kernel, gid_apple_fruit, gid_tree_plant, semantic_threshold=0.5, pattern_threshold=0.1)
    print(f"  Result: {resonance_apple_tree}")
    if resonance_apple_tree.get('resonant'):
         print(kernel.graph.edges[gid_apple_fruit, gid_tree_plant])
    
    # Example 4: No relation - apple (company) vs banana (fruit)
    print(f"\nComparing '{gid_apple_company}' and '{gid_banana_fruit}':")
    resonance_company_banana = detector.detect_resonance_basic(kernel, gid_apple_company, gid_banana_fruit, semantic_threshold=0.5, pattern_threshold=0.1)
    print(f"  Result: {resonance_company_banana}")
    if resonance_company_banana.get('resonant'): # Should not be resonant with these thresholds
         print(kernel.graph.edges[gid_apple_company, gid_banana_fruit])


    print("\n--- Demonstrating SWM Cycle on a Pair ---")
    # Run SWM on apple (fruit) and tree (plant)
    # Patterns should have been abstracted already in the loop above.
    # If not, run_swm_cycle_on_pair will call the abstractor again.
    run_swm_cycle_on_pair(kernel, abstractor, detector, interpreter, gid_apple_fruit, gid_tree_plant)

    print("\n--- Demonstrating SWM Cycle on another Pair (potentially non-resonant with default thresholds) ---")
    # Run SWM on apple (fruit) and apple (company)
    run_swm_cycle_on_pair(kernel, abstractor, detector, interpreter, gid_apple_fruit, gid_apple_company)

    print("\n--- Final Graph State (Before New Tests) ---")
    print(f"Number of Geoids (nodes): {kernel.graph.number_of_nodes()}")
    print(f"Number of Resonance links (edges): {kernel.graph.number_of_edges()}")
    for edge in kernel.graph.edges(data=True):
        print(f"Edge: {edge}")


    print("\n\n--- Task 2: Test Resonance Detection with New Geoids ---")
    
    # Define new Geoid content
    geoid_contents = {
        "code1": "Python is a versatile programming language used for web development, data science, and machine learning.",
        "code2": "Developing applications in Python allows for rapid prototyping and extensive library support.",
        "solar1": "The sun is the star at the center of our solar system.",
        "star1": "A distant star, similar to our sun, might harbor planets.",
        "recipe1": "To bake a cake, you need flour, sugar, eggs, and butter.",
        "car1": "Modern cars are equipped with advanced safety features and navigation systems."
    }

    new_geoid_ids = {}
    print("\n--- Adding New Geoids ---")
    for name, content in geoid_contents.items():
        gid = kernel.add_geoid(content=content, source="new_test_set", geoid_id=f"geoid_{name}")
        new_geoid_ids[name] = gid
        print(f"Added Geoid: ID='{gid}', Content='{content[:50]}...'")

    print("\n--- Abstracting Patterns for New Geoids ---")
    for name, gid in new_geoid_ids.items():
        pattern_str = abstractor.abstract_pattern_basic(kernel, gid)
        retrieved_pattern = kernel.get_geoid(gid).get('dimensions', {}).get('structural_pattern_abstracted')
        print(f"  Geoid '{gid}': Abstracted pattern string = '{pattern_str}', Stored keywords = {retrieved_pattern}")

    # Test Pair 1: Strong Expected Resonance (code1 vs code2)
    print("\n--- Test Pair 1: Strong Expected Resonance (code1 vs code2) ---")
    gid_code1 = new_geoid_ids["code1"]
    gid_code2 = new_geoid_ids["code2"]
    
    print("\n  Testing with default thresholds (semantic=0.7, pattern=0.3):")
    run_swm_cycle_on_pair(kernel, abstractor, detector, interpreter, gid_code1, gid_code2)
    
    print("\n  Testing with custom thresholds (semantic=0.6, pattern=0.2):")
    # Need to reset graph edge if previously added by SWM or direct detection with different thresholds
    if kernel.graph.has_edge(gid_code1, gid_code2): kernel.graph.remove_edge(gid_code1, gid_code2)
    resonance_code_custom1 = detector.detect_resonance_basic(kernel, gid_code1, gid_code2, semantic_threshold=0.6, pattern_threshold=0.2)
    print(f"    Resonance detected (0.6, 0.2): {resonance_code_custom1['resonant']}, Semantic: {resonance_code_custom1['semantic_score']:.4f}, Pattern: {resonance_code_custom1['pattern_score']:.4f}")
    if resonance_code_custom1['resonant']:
        interpretation_text = interpreter.interpret_resonance_placeholder(kernel, gid_code1, gid_code2)
        print(interpretation_text)

    print("\n  Testing with higher thresholds (semantic=0.8, pattern=0.5):")
    if kernel.graph.has_edge(gid_code1, gid_code2): kernel.graph.remove_edge(gid_code1, gid_code2)
    resonance_code_custom2 = detector.detect_resonance_basic(kernel, gid_code1, gid_code2, semantic_threshold=0.8, pattern_threshold=0.5)
    print(f"    Resonance detected (0.8, 0.5): {resonance_code_custom2['resonant']}, Semantic: {resonance_code_custom2['semantic_score']:.4f}, Pattern: {resonance_code_custom2['pattern_score']:.4f}")
    if resonance_code_custom2['resonant']:
        interpretation_text = interpreter.interpret_resonance_placeholder(kernel, gid_code1, gid_code2)
        print(interpretation_text)


    # Test Pair 2: Weak/Moderate Expected Resonance (solar1 vs star1)
    print("\n--- Test Pair 2: Weak/Moderate Expected Resonance (solar1 vs star1) ---")
    gid_solar1 = new_geoid_ids["solar1"]
    gid_star1 = new_geoid_ids["star1"]

    print("\n  Testing with default thresholds (semantic=0.7, pattern=0.3):")
    run_swm_cycle_on_pair(kernel, abstractor, detector, interpreter, gid_solar1, gid_star1)

    print("\n  Testing with custom thresholds (semantic=0.5, pattern=0.1):")
    if kernel.graph.has_edge(gid_solar1, gid_star1): kernel.graph.remove_edge(gid_solar1, gid_star1)
    resonance_solar_custom1 = detector.detect_resonance_basic(kernel, gid_solar1, gid_star1, semantic_threshold=0.5, pattern_threshold=0.1)
    print(f"    Resonance detected (0.5, 0.1): {resonance_solar_custom1['resonant']}, Semantic: {resonance_solar_custom1['semantic_score']:.4f}, Pattern: {resonance_solar_custom1['pattern_score']:.4f}")
    if resonance_solar_custom1['resonant']:
        interpretation_text = interpreter.interpret_resonance_placeholder(kernel, gid_solar1, gid_star1)
        print(interpretation_text)


    # Test Pair 3: No Expected Resonance (recipe1 vs car1)
    print("\n--- Test Pair 3: No Expected Resonance (recipe1 vs car1) ---")
    gid_recipe1 = new_geoid_ids["recipe1"]
    gid_car1 = new_geoid_ids["car1"]

    print("\n  Testing with default thresholds (semantic=0.7, pattern=0.3):")
    run_swm_cycle_on_pair(kernel, abstractor, detector, interpreter, gid_recipe1, gid_car1)
    
    print("\n  Testing with very low thresholds (semantic=0.1, pattern=0.05) to see scores:")
    if kernel.graph.has_edge(gid_recipe1, gid_car1): kernel.graph.remove_edge(gid_recipe1, gid_car1)
    resonance_recipe_custom1 = detector.detect_resonance_basic(kernel, gid_recipe1, gid_car1, semantic_threshold=0.1, pattern_threshold=0.05)
    print(f"    Resonance detected (0.1, 0.05): {resonance_recipe_custom1['resonant']}, Semantic: {resonance_recipe_custom1['semantic_score']:.4f}, Pattern: {resonance_recipe_custom1['pattern_score']:.4f}")
    if resonance_recipe_custom1['resonant']: # Should ideally still be false, but we see the scores
        interpretation_text = interpreter.interpret_resonance_placeholder(kernel, gid_recipe1, gid_car1)
        print(interpretation_text)


    print("\n\n--- Task 3: Qualitative Evaluation of Interpretations ---")
    print("Task 3 is implicitly covered by the printouts from SWM cycles and direct resonance tests above.")
    print("Review the 'Interpretation Placeholder' outputs for any resonant pairs observed during the tests.")
    # Example from original dataset if it was resonant:
    if kernel.graph.has_edge(gid_apple_fruit, gid_banana_fruit): # Check if this edge was added
        print("\n  Re-displaying interpretation for an original resonant pair (apple_fruit, banana_fruit):")
        interpretation_text = interpreter.interpret_resonance_placeholder(kernel, gid_apple_fruit, gid_banana_fruit)
        print(interpretation_text)


    print("\n\n--- Task 4: Test Contradiction Flagging (Revised) ---")
    geoid_C_id = kernel.add_geoid(content="Contradiction Test Geoid", geoid_id="geoid_contradiction_test")
    print(f"Added Geoid for contradiction test: {geoid_C_id}")
    
    # Manually set the contradiction flag
    kernel.graph.nodes[geoid_C_id]['contradiction_flag'] = True
    print(f"Manually set contradiction_flag to True for {geoid_C_id}")
    
    retrieved_geoid_C = kernel.get_geoid(geoid_C_id)
    if retrieved_geoid_C:
        print(f"Retrieved Geoid {geoid_C_id}: contradiction_flag = {retrieved_geoid_C.get('contradiction_flag')}")
        if retrieved_geoid_C.get('contradiction_flag') is True:
            print("  Contradiction flag successfully set and retrieved.")
        else:
            print("  Error: Contradiction flag not set or retrieved correctly.")
    else:
        print(f"  Error: Could not retrieve Geoid {geoid_C_id} for contradiction test.")


    print("\n--- Final Graph State (After New Tests) ---")
    print(f"Number of Geoids (nodes): {kernel.graph.number_of_nodes()}")
    print(f"Number of Resonance links (edges): {kernel.graph.number_of_edges()}")
    # for node_id, node_data in kernel.graph.nodes(data=True):
    #     print(f"Node: {node_id}, Data: {node_data}")
    for edge in kernel.graph.edges(data=True):
        print(f"Edge: {edge}")

    print("\nKimera Kernel v0.1 Demo Complete (including new tests).")
