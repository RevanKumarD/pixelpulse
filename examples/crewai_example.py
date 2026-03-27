"""CrewAI + PixelPulse example.

Shows how to instrument a CrewAI crew to visualize agent activity
in the PixelPulse dashboard.

Requires: pip install pixelpulse[crewai]
"""
from pixelpulse import PixelPulse

# 1. Configure PixelPulse with your crew's agents
pp = PixelPulse(
    agents={
        "researcher": {"team": "research", "role": "Senior Research Analyst"},
        "writer": {"team": "content", "role": "Technical Writer"},
    },
    teams={
        "research": {"label": "Research", "color": "#00d4ff"},
        "content": {"label": "Content", "color": "#ff6ec7"},
    },
)

# 2. Create your CrewAI crew (pseudo-code — replace with your actual crew)
# from crewai import Agent, Task, Crew
#
# researcher = Agent(role="Senior Research Analyst", ...)
# writer = Agent(role="Technical Writer", ...)
# task1 = Task(description="Research latest AI trends", agent=researcher)
# task2 = Task(description="Write a blog post", agent=writer)
# crew = Crew(agents=[researcher, writer], tasks=[task1, task2])

# 3. Instrument the crew
# adapter = pp.adapter("crewai")
# adapter.instrument(crew)

# 4. Start the dashboard (in a separate thread or process)
# import threading
# threading.Thread(target=pp.serve, daemon=True).start()

# 5. Run the crew — events will flow to the dashboard
# crew.kickoff()

print("This is a template example. Uncomment the CrewAI code to use it.")
print("Install CrewAI: pip install pixelpulse[crewai]")
