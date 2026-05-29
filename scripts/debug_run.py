import sys
import os
import traceback

# Add current directory to path
sys.path.append(os.getcwd())

try:
    from lumen.app import main
    print("Starting app...")
    main()
except Exception as e:
    print("CAUGHT EXCEPTION:")
    traceback.print_exc()
    sys.exit(1)
