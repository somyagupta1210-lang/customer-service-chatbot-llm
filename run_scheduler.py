"""Run one scheduler cycle. Schedule this script every minute in Windows Task Scheduler."""
from src.scheduler import UpdateScheduler

if __name__ == "__main__":
    print(UpdateScheduler().process_due())
