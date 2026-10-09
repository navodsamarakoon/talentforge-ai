from skill_relationships import SKILL_RELATIONSHIPS


def main():

    print("=" * 60)
    print("TALENTFORGE SKILL RELATIONSHIPS")
    print("=" * 60)

    print(
        f"\nTotal relationships: "
        f"{len(SKILL_RELATIONSHIPS)}"
    )

    for index, relationship in enumerate(
        SKILL_RELATIONSHIPS,
        start=1
    ):

        print("\n" + "-" * 60)

        print(f"Relationship: {index}")
        print(f"Source: {relationship['source']}")
        print(f"Type: {relationship['relationship']}")
        print(f"Target: {relationship['target']}")

    print("\n" + "=" * 60)
    print("SKILL RELATIONSHIP DEFINITION COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()